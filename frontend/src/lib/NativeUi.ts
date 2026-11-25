// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import { componentPod } from './ArgoComponents';
/** Native resource identities and operations behind the original KFP presentation. */
import {
  argoRequest,
  ArgoRequestError,
  listNativeItems as collection,
  argoArtifactUrl,
  getArgoWorkflow,
  type ArgoWorkflow,
  type ArgoNode,
} from './Argo';
import { listResources, setScheduleSuspended, type NativeResource } from './ArgoResources';
import { V2RuntimeState } from './NativeViewTypes';

export const PIPELINE = 'pipelines.kubeflow.org/pipeline';
export const EXPERIMENT = 'pipelines.kubeflow.org/experiment';
export const DISPLAY_NAME = 'pipelines.kubeflow.org/display-name';
export const DESCRIPTION = 'pipelines.kubeflow.org/description';
export const enc = encodeURIComponent;
export const STORAGE_STATE = 'pipelines.kubeflow.org/storage-state';
export type UiRun = ArgoWorkflow & { live: boolean; storageState?: string };
export const resourceMatches = (resource: NativeResource | undefined, id?: string | null) =>
  !!resource && !!id && (resource.metadata.uid === id || resource.metadata.name === id);
export const resourceId = (resource: NativeResource) =>
  resource.metadata.uid || resource.metadata.name;
export const isRunArchived = (run: UiRun) =>
  (run.storageState || (run.live ? 'AVAILABLE' : 'ARCHIVED')) === 'ARCHIVED';
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
  resource.kind === 'ConfigMap'
    ? resourceId(resource)
    : resource.metadata.labels?.[PIPELINE] || resource.metadata.name;
export const runHref = (run: ArgoWorkflow) => `/runs/details/${enc(run.metadata.uid)}`;
export const pipelineHref = (version: NativeResource) =>
  `/pipelines/details/${enc(pipelineId(version))}/version/${enc(resourceId(version))}`;
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
  const [liveMetadata, summaries, states] = await Promise.all([
    collection<Pick<ArgoWorkflow, 'metadata'>>(
      `/kubernetes/apis/argoproj.io/v1alpha1/namespaces/${enc(namespace)}/workflows`,
      new URLSearchParams({ labelSelector: PIPELINE, limit: '100' }),
      'continue',
      signal,
      'application/json;as=PartialObjectMetadataList;g=meta.k8s.io;v=v1,application/json;q=0.9',
    ),
    collection<ArgoWorkflow>(
      `/argo/api/v1/workflows/${enc(namespace)}`,
      new URLSearchParams({
        'listOptions.labelSelector': PIPELINE,
        'listOptions.limit': '100',
        // Argo's combined live/SQL list needs the total count to paginate both.
        'listOptions.fieldSelector': 'ext.showRemainingItemCount=true',
        fields: [
          'metadata',
          'items.metadata',
          'items.spec.shutdown',
          'items.spec.workflowTemplateRef',
          'items.status.phase',
          'items.status.startedAt',
          'items.status.finishedAt',
          'items.status.message',
        ].join(','),
      }),
      'listOptions.continue',
      signal,
    ),
    listResources(namespace, 'run-state', signal),
  ]);
  const liveIndex = new Map(liveMetadata.map((run) => [run.metadata.uid, run.metadata]));
  const runs = new Map<string, ArgoWorkflow>();
  for (const run of summaries) {
    // Prefer live summaries over their SQL duplicates. Argo's SQLite cache may
    // omit an Archived-labelled CR that still exists, so liveness also needs
    // the lightweight Kubernetes identity index, not an archive label guess.
    if (!runs.get(run.metadata.uid)?.metadata.resourceVersion || run.metadata.resourceVersion)
      runs.set(run.metadata.uid, run);
  }
  for (const metadata of liveIndex.values())
    if (!runs.has(metadata.uid)) runs.set(metadata.uid, { metadata, spec: {} });
  const storage = new Map(
    states
      .filter((state) => state.data?.runId)
      .map((state) => [state.data!.runId, state.data!.storageState]),
  );
  return [...runs.values()].map((summary) => {
    const metadata = liveIndex.get(summary.metadata.uid) || summary.metadata;
    const live = liveIndex.has(metadata.uid) || !!summary.metadata.resourceVersion;
    return {
      ...summary,
      metadata,
      spec: summary.spec || {},
      live,
      archived: !live,
      storageState:
        storage.get(metadata.uid) ||
        metadata.annotations?.[STORAGE_STATE] ||
        (metadata.annotations?.['pipelines.kubeflow.org/parameters'] || live
          ? 'AVAILABLE'
          : 'ARCHIVED'),
    };
  });
}
export async function getUiRun(
  namespace: string,
  uid: string,
  signal?: AbortSignal,
): Promise<UiRun> {
  const runs = await listUiRuns(namespace, signal);
  const run = runs.find((run) => run.metadata.uid === uid);
  if (!run) throw new Error('Run not found in this namespace. It may have been deleted.');
  return {
    ...(await getArgoWorkflow(run, signal)),
    live: run.live,
    storageState: run.storageState,
  };
}
async function setRunStorage(run: ArgoWorkflow, storageState: string) {
  const root = `/kubernetes/api/v1/namespaces/${enc(run.metadata.namespace)}/configmaps`;
  const name = `run-${run.metadata.uid}`;
  let record: NativeResource | undefined;
  try {
    record = await (await argoRequest(`${root}/${enc(name)}`)).json();
  } catch (error) {
    if (!(error instanceof ArgoRequestError) || error.status !== 404) throw error;
  }
  if (record) {
    if (record.data?.runId !== run.metadata.uid)
      throw new Error('Run-state identity does not match.');
    if (record.data.storageState === storageState) return;
    await argoRequest(`${root}/${enc(name)}`, undefined, {
      method: 'PUT',
      body: JSON.stringify({ ...record, data: { ...record.data, storageState } }),
    });
  } else {
    await argoRequest(root, undefined, {
      method: 'POST',
      body: JSON.stringify({
        apiVersion: 'v1',
        kind: 'ConfigMap',
        metadata: {
          name,
          namespace: run.metadata.namespace,
          labels: { 'pipelines.kubeflow.org/resource': 'run-state' },
        },
        data: { runId: run.metadata.uid, storageState },
      }),
    });
  }
}
export async function archiveRun(run: ArgoWorkflow) {
  if (!['Succeeded', 'Failed', 'Error'].includes(run.status?.phase || ''))
    throw new Error('Only completed runs can be archived.');
  await setRunStorage(run, 'ARCHIVED');
}
export async function restoreRun(run: ArgoWorkflow) {
  const experimentId = run.metadata.labels?.[EXPERIMENT];
  if (experimentId) {
    const experiment = (await listResources(run.metadata.namespace, 'experiments')).find(
      (resource) => resourceMatches(resource, experimentId),
    );
    if (!experiment) throw new Error('Experiment not found; cannot restore its run.');
    if (experiment.data?.storageState === 'ARCHIVED')
      throw new Error('Unarchive the experiment first to allow the run to be restored.');
  }
  await setRunStorage(run, 'AVAILABLE');
}
export async function setExperimentStorage(
  namespace: string,
  experiment: NativeResource,
  storageState: string,
) {
  if (!experiment.metadata.uid || !experiment.metadata.resourceVersion)
    throw new Error('Refresh the experiment before updating it.');
  if (experiment.metadata.namespace && experiment.metadata.namespace !== namespace)
    throw new Error('Experiment namespace does not match.');
  if (storageState === 'ARCHIVED') {
    const identities = new Set([experiment.metadata.uid, experiment.metadata.name]);
    // Complete authorization/list checks before any mutation. Suspension precedes
    // child archival, and publishing experiment state is the final step.
    const [schedules, initialRuns] = await Promise.all([
      listResources(namespace, 'cron-workflows'),
      listUiRuns(namespace),
    ]);
    const associatedSchedules = schedules.filter(
      (schedule) =>
        schedule.metadata.namespace === namespace &&
        identities.has(schedule.spec?.workflowMetadata?.labels?.[EXPERIMENT]),
    );
    for (const schedule of associatedSchedules) {
      if (schedule.spec?.suspend) continue;
      if (!schedule.metadata.uid || !schedule.metadata.resourceVersion)
        throw new Error('Refresh the recurring run before archiving its experiment.');
      try {
        await setScheduleSuspended(namespace, schedule, true);
      } catch (error) {
        if (!(error instanceof ArgoRequestError) || error.status !== 404) throw error;
      }
    }
    // Re-list after suspension to include runs created while those requests ran.
    const runs = associatedSchedules.length ? await listUiRuns(namespace) : initialRuns;
    for (const run of runs) {
      if (
        run.metadata.namespace === namespace &&
        identities.has(run.metadata.labels?.[EXPERIMENT] || '')
      )
        await setRunStorage(run, 'ARCHIVED');
    }
  }
  await argoRequest(
    `/kubernetes/api/v1/namespaces/${enc(namespace)}/configmaps/${enc(experiment.metadata.name)}`,
    undefined,
    {
      method: 'PUT',
      body: JSON.stringify({ ...experiment, data: { ...experiment.data, storageState } }),
    },
  );
}
export async function deleteArchivedRun(run: ArgoWorkflow) {
  const root = `/kubernetes/apis/argoproj.io/v1alpha1/namespaces/${enc(run.metadata.namespace)}/workflows/${enc(run.metadata.name)}`;
  let live: ArgoWorkflow | undefined;
  try {
    live = await (await argoRequest(root)).json();
  } catch (error) {
    if (!(error instanceof ArgoRequestError) || error.status !== 404) throw error;
  }
  if (live) {
    if (live.metadata.uid !== run.metadata.uid)
      throw new Error('Workflow name was reused; refresh before deleting.');
    await argoRequest(root, undefined, {
      method: 'DELETE',
      body: JSON.stringify({
        apiVersion: 'v1',
        kind: 'DeleteOptions',
        preconditions: { uid: run.metadata.uid },
      }),
    });
  }
  try {
    await argoRequest(
      `/argo/api/v1/archived-workflows/${enc(run.metadata.uid)}?namespace=${enc(run.metadata.namespace)}`,
      undefined,
      { method: 'DELETE' },
    );
  } catch (error) {
    if (!(error instanceof ArgoRequestError) || error.status !== 404) throw error;
  }
  const statePath = `/kubernetes/api/v1/namespaces/${enc(run.metadata.namespace)}/configmaps/${enc(`run-${run.metadata.uid}`)}`;
  try {
    const state: NativeResource = await (await argoRequest(statePath)).json();
    if (state.data?.runId !== run.metadata.uid || !state.metadata.uid)
      throw new Error('Run-state identity does not match.');
    await argoRequest(statePath, undefined, {
      method: 'DELETE',
      body: JSON.stringify({
        apiVersion: 'v1',
        kind: 'DeleteOptions',
        preconditions: { uid: state.metadata.uid },
      }),
    });
  } catch (error) {
    if (!(error instanceof ArgoRequestError) || error.status !== 404) throw error;
  }
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
  if (!plural && resource.kind !== 'ConfigMap') throw new Error('Unsupported resource kind.');
  const path =
    resource.kind === 'ConfigMap'
      ? `/kubernetes/api/v1/namespaces/${enc(namespace)}/configmaps/${enc(resource.metadata.name)}`
      : `/kubernetes/apis/argoproj.io/v1alpha1/namespaces/${enc(namespace)}/${plural}/${enc(resource.metadata.name)}`;
  await argoRequest(path, undefined, {
    method: 'DELETE',
    body: JSON.stringify({
      apiVersion: 'v1',
      kind: 'DeleteOptions',
      propagationPolicy: 'Orphan',
      preconditions: { uid: resource.metadata.uid },
    }),
  });
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
export type TaskLogSource = 'live' | 'archive';
export interface TaskLogUpdate {
  source: TaskLogSource;
  lines: string[];
}
const TERMINAL_PHASES = new Set(['Succeeded', 'Failed', 'Error', 'Skipped', 'Omitted']);

function parseLogEntry(line: string): string {
  const entry = JSON.parse(line);
  if (entry.error) throw new Error(entry.error.message || 'Log stream failed.');
  return entry.result.content as string;
}

/** Yield Argo Server's newline-delimited log stream as lines arrive, never buffering it whole. */
async function* livePodLogs(
  run: ArgoWorkflow,
  podName: string,
  follow: boolean,
  signal?: AbortSignal,
): AsyncGenerator<TaskLogUpdate> {
  const options = new URLSearchParams({
    podName,
    'logOptions.container': 'main',
    'logOptions.follow': String(follow),
  });
  const response = await argoRequest(
    `/argo/api/v1/workflows/${enc(run.metadata.namespace)}/${enc(run.metadata.name)}/log?${options}`,
    signal,
  );
  const reader = response.body?.getReader();
  if (!reader) {
    const lines = (await response.text()).split('\n').filter(Boolean).map(parseLogEntry);
    if (lines.length) yield { source: 'live', lines };
    return;
  }
  const decoder = new TextDecoder();
  let buffer = '';
  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    const parts = buffer.split('\n');
    buffer = done ? '' : parts.pop() || '';
    const lines = parts.filter(Boolean).map(parseLogEntry);
    if (lines.length) yield { source: 'live', lines };
    if (done) return;
  }
}

async function findTaskPod(run: ArgoWorkflow, node: ArgoNode, signal?: AbortSignal) {
  const query = new URLSearchParams({
    labelSelector: `workflows.argoproj.io/workflow=${run.metadata.name}`,
  });
  const pods = await (
    await argoRequest(
      `/kubernetes/api/v1/namespaces/${enc(run.metadata.namespace)}/pods?${query}`,
      signal,
    )
  ).json();
  return pods.items?.find(
    (pod: { metadata: { annotations?: Record<string, string> } }) =>
      pod.metadata.annotations?.['workflows.argoproj.io/node-id'] === node.id,
  ) as { metadata: { name: string } } | undefined;
}

/**
 * Task logs in full. A running task streams live from its pod and keeps
 * following until the pod finishes. A finished task reads the complete
 * `main-logs` artifact that Argo archived, which also serves runs whose
 * workflow object or pod is gone; if nothing was archived, the pod's full log
 * is used while the pod still exists.
 */
export async function* streamTaskLogs(
  run: ArgoWorkflow,
  node: ArgoNode,
  signal?: AbortSignal,
): AsyncGenerator<TaskLogUpdate> {
  node = componentPod(run, node);
  const archived = !!node.outputs?.artifacts?.some((artifact) => artifact.name === 'main-logs');
  const finished = TERMINAL_PHASES.has(node.phase || '');
  if (!run.archived && (!finished || !archived)) {
    const pod = await findTaskPod(run, node, signal);
    if (pod) {
      yield* livePodLogs(run, pod.metadata.name, !finished, signal);
      return;
    }
    if (!archived)
      throw new Error(
        finished
          ? 'The task pod is gone and its logs were not archived before deletion.'
          : 'The task pod is not available yet.',
      );
  }
  if (!archived) throw new Error('No archived logs were recorded for this task.');
  const text = await (await argoRequest(argoArtifactUrl(run, node, 'main-logs'), signal)).text();
  yield { source: 'archive', lines: text.replace(/\n$/, '').split('\n') };
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
