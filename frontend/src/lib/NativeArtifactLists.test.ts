// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import { afterEach, expect, it, vi } from 'vitest';
import { submitRun, type NativeResource } from './ArgoResources';
import { createSchedule } from './NativeScheduling';

const version: NativeResource = {
  apiVersion: 'argoproj.io/v1alpha1',
  kind: 'WorkflowTemplate',
  metadata: { name: 'list-version', uid: 'version-id' },
  spec: {
    entrypoint: 'consume',
    templates: [
      {
        name: 'consume',
        metadata: { annotations: { 'pipelines.kubeflow.org/artifact-list-staging': 'v1' } },
        container: { image: 'user-image', volumeMounts: [{ name: 'data', mountPath: '/data' }] },
        volumes: [{ name: 'data', emptyDir: {} }],
        initContainers: [
          {
            name: 'kfp-stage-artifacts',
            env: [{ name: 'KFP_STAGING_REPOSITORY', value: '{}' }],
            volumeMounts: [{ name: 'data', mountPath: '/data' }],
          },
        ],
      },
    ],
  },
};
function mockRepository() {
  const bodies: any[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (path: string, init?: RequestInit) => {
      if (init?.method === 'POST') {
        bodies.push(JSON.parse(String(init.body)));
        return new Response('{}');
      }
      expect(path).toContain('/configmaps/artifact-repositories');
      return new Response(
        JSON.stringify({
          metadata: {
            annotations: { 'workflows.argoproj.io/default-artifact-repository': 'default' },
          },
          data: {
            default: JSON.stringify({
              s3: {
                bucket: 'argo-artifacts',
                endpoint: 'minio:9000',
                accessKeySecret: { name: 'storage', key: 'access' },
                secretKeySecret: { name: 'storage', key: 'secret' },
              },
            }),
          },
        }),
      );
    }),
  );
  return bodies;
}
afterEach(() => vi.unstubAllGlobals());

it('binds immutable version copies for UI runs without reading or exposing Secret values', async () => {
  vi.stubGlobal('crypto', undefined); // HTTP deployments need no Web Crypto for volume naming.
  const original = structuredClone(version);
  const bodies = mockRepository();
  await submitRun('team', version, {}, 'experiment');
  const template = bodies[0].workflow.spec.templates[0];
  expect(template.container).toEqual(version.spec!.templates[0].container);
  const secret = template.volumes.find((v: any) => v.secret);
  expect(secret.secret.secretName).toBe('storage');
  expect(template.initContainers[0].volumeMounts).toContainEqual(
    expect.objectContaining({ name: secret.name, readOnly: true }),
  );
  expect(version).toEqual(original);
  expect(vi.mocked(fetch).mock.calls.every(([url]) => !String(url).includes('/secrets/'))).toBe(
    true,
  );
});

it('binds the same init-only credentials for UI schedules', async () => {
  const bodies = mockRepository();
  await createSchedule(
    'team',
    {
      apiVersion: 'argoproj.io/v1alpha1',
      kind: 'CronWorkflow',
      metadata: { name: 'schedule' },
      spec: { workflowSpec: version.spec },
    },
    {
      trigger: { periodic_schedule: { interval_second: '60' } },
      catchup: false,
      maxConcurrentRuns: '1',
    },
  );
  const template = bodies[0].cronWorkflow.spec.workflowSpec.templates[0];
  expect(template.volumes.some((v: any) => v.secret)).toBe(true);
  expect(template.container).toEqual(version.spec!.templates[0].container);
});
