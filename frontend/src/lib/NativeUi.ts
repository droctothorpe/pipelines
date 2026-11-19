// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
/** Native resource identities and operations behind the original KFP presentation. */
import {
  argoRequest,
  listNativeItems as collection,
  argoArtifactUrl,
  getArgoWorkflow,
  type ArgoWorkflow,
  type ArgoNode,
} from './Argo';
import { listResources, type NativeResource } from './ArgoResources';
import { V2RuntimeState } from './NativeViewTypes';

export const PIPELINE = 'pipelines.kubeflow.org/pipeline';
export const EXPERIMENT = 'pipelines.kubeflow.org/experiment';
export const DISPLAY_NAME = 'pipelines.kubeflow.org/display-name';
export const DESCRIPTION = 'pipelines.kubeflow.org/description';
export const enc = encodeURIComponent;
export type UiRun = ArgoWorkflow & { live: boolean };
export const displayName = (resource: {
  metadata: { name: string; annotations?: Record<string, string> };
  data?: Record<string, string>;
}) =>
  resource.data?.displayName ||
  resource.metadata.annotations?.[DISPLAY_NAME] ||
  resource.metadata.name;
export const description = (resource: NativeResource) =>
  resource.data?.description || resource.metadata.annotations?.[DESCRIPTION] || '';
export const pipelineId = (resource: NativeResource) =>
  resource.metadata.labels?.[PIPELINE] || resource.metadata.name;
export const runHref = (run: ArgoWorkflow) => `/runs/details/${enc(run.metadata.uid)}`;
export const pipelineHref = (version: NativeResource) =>
  `/pipelines/details/${enc(pipelineId(version))}/version/${enc(version.metadata.name)}`;
export const experimentHref = (name: string) => `/experiments/details/${enc(name)}`;
export function runState(run: ArgoWorkflow): V2RuntimeState {
  if (run.status?.message === 'terminated' || run.spec.shutdown === 'Terminate')
    return V2RuntimeState.CANCELED;
  return (
    (
      {
        Pending: V2RuntimeState.PENDING,
        Running: V2RuntimeState.RUNNING,
        Succeeded: V2RuntimeState.SUCCEEDED,
        Failed: V2RuntimeState.FAILED,
        Error: V2RuntimeState.FAILED,
      } as Record<string, V2RuntimeState>
    )[run.status?.phase || ''] || V2RuntimeState.RUNTIME_STATE_UNSPECIFIED
  );
}

export async function listUiRuns(namespace: string, signal?: AbortSignal): Promise<UiRun[]> {
  const [live, archive] = await Promise.all([
    collection<ArgoWorkflow>(
      `/kubernetes/apis/argoproj.io/v1alpha1/namespaces/${enc(namespace)}/workflows`,
      new URLSearchParams({ labelSelector: PIPELINE, limit: '100' }),
      'continue',
      signal,
    ),
    collection<ArgoWorkflow>(
      '/argo/api/v1/archived-workflows',
      new URLSearchParams({
        namespace,
        'listOptions.labelSelector': PIPELINE,
        'listOptions.limit': '100',
      }),
      'listOptions.continue',
      signal,
    ),
  ]);
  const runs = new Map(
    archive.map((run) => [run.metadata.uid, { ...run, archived: true, live: false }]),
  );
  for (const run of live) runs.set(run.metadata.uid, { ...run, archived: false, live: true });
  return [...runs.values()];
}
export async function getUiRun(
  namespace: string,
  uid: string,
  signal?: AbortSignal,
): Promise<UiRun> {
  const runs = await listUiRuns(namespace, signal);
  const run = runs.find((run) => run.metadata.uid === uid);
  if (!run) throw new Error('Run not found in this namespace. It may have been deleted.');
  return { ...(await getArgoWorkflow(run, signal)), live: run.live };
}
export async function archiveRun(run: ArgoWorkflow) {
  if (!['Succeeded', 'Failed', 'Error'].includes(run.status?.phase || ''))
    throw new Error('Only completed runs can be archived.');
  // Verify a durable archive exists before removing the live CR (and its pods).
  const archived = await (
    await argoRequest(
      `/argo/api/v1/archived-workflows/${enc(run.metadata.uid)}?namespace=${enc(run.metadata.namespace)}`,
    )
  ).json();
  if (archived.metadata?.uid !== run.metadata.uid)
    throw new Error('Argo has not archived this run yet. Try again shortly.');
  await argoRequest(
    `/kubernetes/apis/argoproj.io/v1alpha1/namespaces/${enc(run.metadata.namespace)}/workflows/${enc(run.metadata.name)}`,
    undefined,
    {
      method: 'DELETE',
      body: JSON.stringify({
        apiVersion: 'v1',
        kind: 'DeleteOptions',
        preconditions: { uid: run.metadata.uid },
      }),
    },
  );
}
export async function deleteArchivedRun(run: ArgoWorkflow) {
  await argoRequest(
    `/argo/api/v1/archived-workflows/${enc(run.metadata.uid)}?namespace=${enc(run.metadata.namespace)}`,
    undefined,
    { method: 'DELETE' },
  );
}
export async function deleteNativeResource(namespace: string, resource: NativeResource) {
  if (!resource.metadata.uid)
    throw new Error('Refresh before deleting this resource; its UID is missing.');
  const plural =
    resource.kind === 'WorkflowTemplate'
      ? 'workflowtemplates'
      : resource.kind === 'CronWorkflow'
        ? 'cronworkflows'
        : undefined;
  if (!plural) throw new Error('Unsupported resource kind.');
  await argoRequest(
    `/kubernetes/apis/argoproj.io/v1alpha1/namespaces/${enc(namespace)}/${plural}/${enc(resource.metadata.name)}`,
    undefined,
    {
      method: 'DELETE',
      body: JSON.stringify({
        apiVersion: 'v1',
        kind: 'DeleteOptions',
        propagationPolicy: 'Orphan',
        preconditions: { uid: resource.metadata.uid },
      }),
    },
  );
}
export async function listVersions(namespace: string, signal?: AbortSignal) {
  return listResources(namespace, 'workflow-templates', signal);
}
export async function downloadArtifact(run: ArgoWorkflow, node: ArgoNode, port: string) {
  const response = await argoRequest(argoArtifactUrl(run, node, port));
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement('a');
  link.href = url;
  link.download = port;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
export async function taskLogs(run: ArgoWorkflow, node: ArgoNode, signal?: AbortSignal) {
  if (node.outputs?.artifacts?.some((artifact) => artifact.name === 'main-logs'))
    return (await (await argoRequest(argoArtifactUrl(run, node, 'main-logs'), signal)).text())
      .split('\n')
      .slice(-200);
  if (run.archived) throw new Error('No archived logs were recorded for this task.');
  const query = new URLSearchParams({
    labelSelector: `workflows.argoproj.io/workflow=${run.metadata.name}`,
  });
  const pods = await (
    await argoRequest(
      `/kubernetes/api/v1/namespaces/${enc(run.metadata.namespace)}/pods?${query}`,
      signal,
    )
  ).json();
  const pod = pods.items?.find(
    (pod: { metadata: { annotations?: Record<string, string> } }) =>
      pod.metadata.annotations?.['workflows.argoproj.io/node-id'] === node.id,
  );
  if (!pod)
    throw new Error(
      'The task pod is not available yet, or its logs were not archived before pod deletion.',
    );
  const options = new URLSearchParams({
    podName: pod.metadata.name,
    'logOptions.container': 'main',
    'logOptions.follow': 'false',
    'logOptions.tailLines': '200',
  });
  const text = await (
    await argoRequest(
      `/argo/api/v1/workflows/${enc(run.metadata.namespace)}/${enc(run.metadata.name)}/log?${options}`,
      signal,
    )
  ).text();
  return text
    .split('\n')
    .filter(Boolean)
    .map((line) => {
      const entry = JSON.parse(line);
      if (entry.error) throw new Error(entry.error.message || 'Log stream failed.');
      return entry.result.content as string;
    });
}
export async function retryRun(run: ArgoWorkflow) {
  const path = `/argo/api/v1/workflows/${enc(run.metadata.namespace)}/${enc(run.metadata.name)}`;
  const current = await (await argoRequest(path)).json();
  if (current.metadata?.uid !== run.metadata.uid)
    throw new Error('This workflow name was reused. Refresh before retrying.');
  await argoRequest(`${path}/retry`, undefined, {
    method: 'PUT',
    body: JSON.stringify({
      namespace: run.metadata.namespace,
      name: run.metadata.name,
      restartSuccessful: false,
    }),
  });
}
