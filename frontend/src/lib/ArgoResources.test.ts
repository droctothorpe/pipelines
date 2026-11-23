// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0

import { afterEach, expect, it, vi } from 'vitest';
import { setArgoToken } from './Argo';
import {
  createResource,
  deleteExperiment,
  setScheduleSuspended,
  submitRun,
  workflowAction,
  type NativeResource,
} from './ArgoResources';

const version: NativeResource = {
  apiVersion: 'argoproj.io/v1alpha1',
  kind: 'WorkflowTemplate',
  metadata: {
    name: 'pipeline-abc123',
    labels: {
      'pipelines.kubeflow.org/pipeline': 'pipeline',
      'pipelines.kubeflow.org/version': 'abc123',
    },
  },
  spec: {},
};
// The namespace's Argo artifact repositories, which runs bind to at submit.
const repositories = {
  metadata: { annotations: { 'workflows.argoproj.io/default-artifact-repository': 'default' } },
  data: {
    default: 's3:\n  bucket: argo-artifacts\n  endpoint: minio:9000\n',
    archive: 's3:\n  bucket: new-bucket\n  endpoint: minio:9000\n',
    exports: 'gcs:\n  bucket: new-bucket\n',
  },
};
const mock = () =>
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) =>
      String(url).endsWith('/configmaps/artifact-repositories')
        ? new Response(JSON.stringify(repositories))
        : new Response('{}'),
    ),
  );
const submission = () => vi.mocked(fetch).mock.calls.find(([, init]) => init?.method === 'POST')!;
afterEach(() => {
  vi.unstubAllGlobals();
  setArgoToken('');
});

it('creates versions without an update/overwrite fallback', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response('{}', { status: 409 })),
  );
  await expect(createResource('team', 'workflow-templates', version)).rejects.toThrow('409');
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(vi.mocked(fetch).mock.calls[0][1]?.method).toBe('POST');
});

it('rejects manifests targeting another namespace', async () => {
  mock();
  await expect(
    createResource('team', 'workflow-templates', {
      ...version,
      metadata: { ...version.metadata, namespace: 'someone-else' },
    }),
  ).rejects.toThrow('namespace team');
  expect(fetch).not.toHaveBeenCalled();
});

it('submits native workflows with version and experiment labels', async () => {
  mock();
  setArgoToken('test-namespace-token');
  const bound = structuredClone(version);
  bound.metadata.annotations = { 'pipelines.kubeflow.org/artifact-root-binding': 'v1' };
  await submitRun('team', bound, { factor: '1.2' }, 'experiment-a');
  const [url, options] = submission();
  expect(url).toBe('/argo/api/v1/workflows/team');
  expect(options?.headers).toMatchObject({ Authorization: 'Bearer test-namespace-token' });
  const body = JSON.parse(options?.body as string);
  expect(body.workflow.spec.workflowTemplateRef.name).toBe(version.metadata.name);
  expect(body.workflow.metadata.labels['pipelines.kubeflow.org/experiment']).toBe('experiment-a');
  // No root anywhere: the run follows the namespace's default repository.
  expect(body.workflow.metadata.annotations['pipelines.kubeflow.org/pipeline-root']).toBe(
    's3://argo-artifacts',
  );
  expect(body.workflow.metadata.annotations['pipelines.kubeflow.org/artifact-bucket']).toBe(
    'argo-artifacts',
  );
  expect(body.workflow.spec.artifactRepositoryRef).toBeUndefined();
  // A hand-written template without bindings is submitted as it is.
  vi.mocked(fetch).mockClear();
  await submitRun('team', version, {}, 'experiment-a');
  const plain = JSON.parse(submission()[1]?.body as string).workflow;
  expect(plain.metadata.annotations['pipelines.kubeflow.org/pipeline-root']).toBeUndefined();
});

it('refuses a root no namespace repository serves, before submitting anything', async () => {
  mock();
  await expect(
    submitRun('team', version, {}, '', 'Nowhere', '', '', 's3://elsewhere/x'),
  ).rejects.toThrow('No artifact repository in this namespace serves s3://elsewhere');
  expect(vi.mocked(fetch).mock.calls.every(([, init]) => init?.method !== 'POST')).toBe(true);
});

it.each([
  ['s3://new-bucket/a/b', 'archive'],
  ['gs://new-bucket/a/b', 'exports'],
])('applies a custom pipeline root without changing the version: %s', async (root, entry) => {
  mock();
  const compiled = structuredClone(version);
  compiled.metadata.annotations = {
    'pipelines.kubeflow.org/artifact-root-binding': 'v1',
    'pipelines.kubeflow.org/artifact-repository': 's3://old-bucket',
  };
  compiled.spec = {
    entrypoint: 'root',
    templates: [
      {
        name: 'root',
        outputs: {
          artifacts: [
            {
              name: 'data',
              s3: {
                key: '{{workflow.annotations.pipelines.kubeflow.org/artifact-key-prefix}}data',
              },
            },
          ],
        },
      },
    ],
  };
  const before = JSON.stringify(compiled);
  await submitRun('team', compiled, {}, '', 'Custom root', '', '', root);
  const body = JSON.parse(submission()[1]?.body as string).workflow;
  expect(body.metadata.annotations['pipelines.kubeflow.org/artifact-repository']).toBe(root);
  expect(body.metadata.annotations['pipelines.kubeflow.org/artifact-bucket']).toBe('new-bucket');
  expect(body.metadata.annotations['pipelines.kubeflow.org/artifact-key-prefix']).toBe('a/b/');
  // The entry serving the root is selected; artifacts stay key-only.
  expect(body.spec.artifactRepositoryRef).toEqual({ key: entry });
  expect(body.spec.workflowTemplateRef.name).toBe(version.metadata.name);
  expect(JSON.stringify(compiled)).toBe(before);
});

it('deletes only the experiment ConfigMap, using its UID precondition', async () => {
  mock();
  await expect(
    deleteExperiment('team', {
      apiVersion: 'v1',
      kind: 'ConfigMap',
      metadata: { name: 'experiment-a' },
    }),
  ).rejects.toThrow('UID is missing');
  expect(fetch).not.toHaveBeenCalled();
  await deleteExperiment('team', {
    apiVersion: 'v1',
    kind: 'ConfigMap',
    metadata: { name: 'experiment-a', uid: 'uid-a' },
  });
  expect(fetch).toHaveBeenCalledTimes(1);
  const [url, options] = vi.mocked(fetch).mock.calls[0];
  expect(url).toBe('/kubernetes/api/v1/namespaces/team/configmaps/experiment-a');
  expect(JSON.parse(options?.body as string).preconditions).toEqual({ uid: 'uid-a' });
});

it('preserves resourceVersion when changing a CronWorkflow', async () => {
  mock();
  await setScheduleSuspended(
    'team',
    {
      ...version,
      kind: 'CronWorkflow',
      metadata: { name: 'schedule', resourceVersion: '123' },
      spec: { schedule: '0 9 * * *', suspend: true },
    },
    false,
  );
  const body = JSON.parse(vi.mocked(fetch).mock.calls[0][1]?.body as string);
  expect(body.cronWorkflow.metadata.resourceVersion).toBe('123');
  expect(body.cronWorkflow.spec.suspend).toBe(false);
});

it('refuses a same-name replacement before a workflow mutation', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            metadata: { name: 'run', namespace: 'team', uid: 'replacement' },
            spec: {},
          }),
        ),
    ),
  );
  await expect(
    workflowAction(
      { metadata: { name: 'run', namespace: 'team', uid: 'original' }, spec: {} },
      'resume',
    ),
  ).rejects.toThrow('reused');
  expect(vi.mocked(fetch).mock.calls.every(([, options]) => !options?.method)).toBe(true);
});

it('reports denied workflow operations without retrying through another backend', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response('{}', { status: 403 })),
  );
  await expect(
    workflowAction(
      { metadata: { name: 'run', namespace: 'team', uid: 'uid' }, spec: {} },
      'resume',
    ),
  ).rejects.toThrow('403');
  expect(fetch).toHaveBeenCalledTimes(1);
});
