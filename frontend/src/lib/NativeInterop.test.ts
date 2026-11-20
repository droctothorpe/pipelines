// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import { afterEach, describe, expect, it, vi } from 'vitest';
import { archiveRun, listUiRuns } from './NativeUi';
import type { ArgoWorkflow } from './Argo';

const run: ArgoWorkflow = {
  metadata: {
    name: 'sdk-run',
    namespace: 'team',
    uid: 'run-uid',
    resourceVersion: '1',
    annotations: { 'pipelines.kubeflow.org/storage-state': 'AVAILABLE' },
  },
  spec: {},
  status: { phase: 'Succeeded' },
};
afterEach(() => vi.unstubAllGlobals());
describe('SDK/UI shared resource semantics', () => {
  it('uses SDK archive flags rather than treating SQL persistence as user archival', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async (path: string) =>
          new Response(
            JSON.stringify(
              path.includes('/configmaps')
                ? {
                    items: [
                      {
                        metadata: { name: 'run-run-uid' },
                        data: { runId: 'run-uid', storageState: 'ARCHIVED' },
                      },
                    ],
                  }
                : path.includes('/kubernetes/apis/')
                  ? { items: [run] }
                  : { items: [run] },
            ),
          ),
      ),
    );
    const runs = await listUiRuns('team');
    expect(runs[0]).toMatchObject({ live: true, storageState: 'ARCHIVED' });
  });
  it('keeps an SDK run active after Argo deletes its live CR', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async (path: string) =>
          new Response(
            JSON.stringify({
              items: path.includes('/api/v1/workflows/')
                ? [{ ...run, metadata: { ...run.metadata, resourceVersion: undefined } }]
                : [],
            }),
          ),
      ),
    );
    expect((await listUiRuns('team'))[0]).toMatchObject({ live: false, storageState: 'AVAILABLE' });
  });
  it('archives by writing a run-state ConfigMap, never by deleting the workflow', async () => {
    const requests: Array<{ path: string; init?: RequestInit }> = [];
    vi.stubGlobal(
      'fetch',
      vi.fn(async (path: string, init?: RequestInit) => {
        requests.push({ path, init });
        return new Response('{}', { status: init?.method === 'POST' ? 201 : 404 });
      }),
    );
    await archiveRun(run);
    expect(requests.some((request) => request.init?.method === 'DELETE')).toBe(false);
    const request = requests.find((request) => request.init?.method === 'POST')!;
    expect(request.path).toBe('/kubernetes/api/v1/namespaces/team/configmaps');
    expect(JSON.parse(String(request.init?.body))).toMatchObject({
      kind: 'ConfigMap',
      data: { runId: 'run-uid', storageState: 'ARCHIVED' },
    });
  });
});
