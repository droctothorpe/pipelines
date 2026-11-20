// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  archiveRun,
  deleteNativeResource,
  getUiRun,
  listUiRuns,
  retryRun,
  restoreRun,
  setExperimentStorage,
  taskLogs,
} from './NativeUi';
import { listResources } from './ArgoResources';
import type { ArgoWorkflow } from './Argo';
const run: ArgoWorkflow = {
  metadata: { name: 'same-name', namespace: 'team', uid: 'live-uid', resourceVersion: '12' },
  spec: {},
  status: { phase: 'Succeeded' },
};
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
afterEach(() => vi.unstubAllGlobals());

describe('native resource adapter for the stock UI', () => {
  it('deduplicates by UID and distinguishes live CRs from automatically archived SQL rows', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (path: string) =>
        response({
          items: path.includes('/configmaps')
            ? []
            : path.startsWith('/kubernetes/')
              ? [{ metadata: run.metadata }]
              : [
                  {
                    ...run,
                    metadata: { ...run.metadata, resourceVersion: undefined },
                    status: { phase: 'Failed' },
                  },
                  {
                    ...run,
                    metadata: { ...run.metadata, uid: 'older-uid', resourceVersion: undefined },
                  },
                  {
                    ...run,
                    metadata: {
                      ...run.metadata,
                      labels: { 'workflows.argoproj.io/workflow-archiving-status': 'Persisted' },
                    },
                  },
                  {
                    ...run,
                    metadata: { ...run.metadata, resourceVersion: undefined },
                    status: { phase: 'Failed' },
                  },
                ],
        }),
      ),
    );
    const runs = await listUiRuns('team');
    expect(runs.map((run) => [run.metadata.uid, run.live])).toEqual([
      ['live-uid', true],
      ['older-uid', false],
    ]);
    expect(runs[0].status?.phase).toBe('Succeeded');
    expect(runs[0].storageState).toBe('AVAILABLE');
  });
  it('keeps physically live archived-label workflows live when Argo lists only their SQL summary', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (path: string) =>
        response({
          items: path.includes('/configmaps')
            ? []
            : path.startsWith('/kubernetes/')
              ? [
                  {
                    metadata: {
                      ...run.metadata,
                      labels: { 'workflows.argoproj.io/workflow-archiving-status': 'Archived' },
                    },
                  },
                ]
              : [{ ...run, metadata: { ...run.metadata, resourceVersion: undefined } }],
        }),
      ),
    );
    const [listed] = await listUiRuns('team');
    expect(listed.live).toBe(true);
    expect(listed.archived).toBe(false);
  });
  it('retains new live identities while the Argo summary cache catches up', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (path: string) =>
        response({
          items: path.startsWith('/kubernetes/apis/') ? [{ metadata: run.metadata }] : [],
        }),
      ),
    );
    const [listed] = await listUiRuns('team');
    expect(listed.metadata.uid).toBe('live-uid');
    expect(listed.live).toBe(true);
    expect(listed.status).toBeUndefined();
  });
  it('polls projected workflow summaries rather than full Kubernetes workflow bodies', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (path: string) =>
        response({
          items: path.includes('/configmaps')
            ? []
            : [{ ...run, metadata: { ...run.metadata, resourceVersion: '12' } }],
        }),
      ),
    );
    await listUiRuns('team');
    const urls = vi
      .mocked(fetch)
      .mock.calls.map(([path]) => new URL(String(path), 'http://localhost'));
    const inventory = urls.find((url) => url.pathname === '/argo/api/v1/workflows/team');
    expect(inventory).toBeDefined();
    expect(inventory!.searchParams.get('fields')).toContain('items.status.phase');
    expect(inventory!.searchParams.get('fields')).not.toContain('items.status.nodes');
    expect(inventory!.searchParams.get('fields')).not.toContain('items.spec.templates');
    expect(inventory!.searchParams.get('listOptions.fieldSelector')).toBe(
      'ext.showRemainingItemCount=true',
    );
    const metadataRequest = vi
      .mocked(fetch)
      .mock.calls.find(([path]) => String(path).includes('/kubernetes/apis/'));
    expect(new Headers(metadataRequest?.[1]?.headers).get('Accept')).toContain(
      'as=PartialObjectMetadataList',
    );
  });
  it('follows Kubernetes and Argo continuation tokens', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (path: string) => {
        const url = new URL(path, 'http://localhost');
        const key = path.startsWith('/kubernetes/') ? 'continue' : 'listOptions.continue';
        return response(
          url.searchParams.has(key)
            ? { items: [run] }
            : { items: [], metadata: { continue: 'next+/page' } },
        );
      }),
    );
    expect(await listUiRuns('team')).toHaveLength(1);
    expect(fetch).toHaveBeenCalledTimes(6);
    expect(
      vi.mocked(fetch).mock.calls.filter(([url]) => String(url).includes('next%2B%2Fpage')),
    ).toHaveLength(3);
  });
  it('follows continuation tokens for versions, schedules and experiments', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (path: string) =>
        response(
          path.includes('continue=')
            ? { items: [{ metadata: { name: 'second' } }] }
            : { items: [{ metadata: { name: 'first' } }], metadata: { continue: 'next' } },
        ),
      ),
    );
    for (const kind of ['workflow-templates', 'cron-workflows', 'experiments'] as const)
      expect((await listResources('team', kind)).map((resource) => resource.metadata.name)).toEqual(
        ['first', 'second'],
      );
  });
  it('restores native TypeMeta omitted by Argo Server list responses', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        response({ items: [{ metadata: { name: 'template', uid: 'uid' }, spec: {} }] }),
      ),
    );
    expect(await listResources('team', 'workflow-templates')).toEqual([
      expect.objectContaining({ apiVersion: 'argoproj.io/v1alpha1', kind: 'WorkflowTemplate' }),
    ]);
    expect(await listResources('team', 'cron-workflows')).toEqual([
      expect.objectContaining({ apiVersion: 'argoproj.io/v1alpha1', kind: 'CronWorkflow' }),
    ]);
  });
  it('fails visibly rather than looping or duplicating on a repeated continuation token', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        response({
          items: [{ metadata: { name: 'a', uid: 'a' } }],
          metadata: { continue: 'same' },
        }),
      ),
    );
    await expect(listUiRuns('team')).rejects.toThrow('repeated a pagination token');
  });
  it('treats a repeated continuation token with an empty page as the end of the list', async () => {
    // Argo Server's merged live/archived list ends this way once rows deduplicate.
    let calls = 0;
    vi.stubGlobal(
      'fetch',
      vi.fn(async (path: string) => {
        if (!path.startsWith('/argo/api/v1/workflows/team')) return response({ items: [] });
        calls += 1;
        return response(
          calls === 1
            ? {
                items: [
                  { metadata: { name: 'run', uid: 'uid-1' }, status: { phase: 'Succeeded' } },
                ],
                metadata: { continue: '252' },
              }
            : { items: [], metadata: { continue: '252' } },
        );
      }),
    );
    const runs = await listUiRuns('team');
    expect(runs.map((run) => run.metadata.name)).toEqual(['run']);
    expect(calls).toBe(2);
  });
  it('never confuses a reused workflow name with an older run identity', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (path: string) =>
        response(
          path.includes('/same-name')
            ? { ...run, metadata: { ...run.metadata, uid: 'replacement-uid' } }
            : path.includes('/api/v1/workflows/')
              ? { items: [run] }
              : { items: [] },
        ),
      ),
    );
    await expect(getUiRun('team', 'live-uid')).rejects.toThrow('name was reused');
  });
  it('updates archive state with the existing ConfigMap UID and resourceVersion', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        response({
          apiVersion: 'v1',
          kind: 'ConfigMap',
          metadata: { name: 'run-live-uid', uid: 'state-uid', resourceVersion: '7' },
          data: { runId: 'live-uid', storageState: 'AVAILABLE' },
        }),
      ),
    );
    await archiveRun(run);
    const [url, options] = vi.mocked(fetch).mock.calls[1];
    expect(url).toBe('/kubernetes/api/v1/namespaces/team/configmaps/run-live-uid');
    expect(options?.method).toBe('PUT');
    expect(JSON.parse(String(options?.body))).toMatchObject({
      metadata: { uid: 'state-uid', resourceVersion: '7' },
      data: { storageState: 'ARCHIVED' },
    });
    expect(vi.mocked(fetch).mock.calls.some(([, options]) => options?.method === 'DELETE')).toBe(
      false,
    );
  });
  it.each([403, 500])('does not write archive state when reading it returns %s', async (status) => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => response({}, status)),
    );
    await expect(archiveRun(run)).rejects.toThrow(`(${status})`);
    expect(fetch).toHaveBeenCalledTimes(1);
  });
  it('does not delete a running workflow through Archive', async () => {
    vi.stubGlobal('fetch', vi.fn());
    await expect(archiveRun({ ...run, status: { phase: 'Running' } })).rejects.toThrow(
      'Only completed runs',
    );
    expect(fetch).not.toHaveBeenCalled();
  });
  it('archives experiment children before hiding the experiment, and does not restore them', async () => {
    const experiment = {
      apiVersion: 'v1',
      kind: 'ConfigMap',
      metadata: {
        name: 'experiment-map',
        uid: 'experiment-uid',
        namespace: 'team',
        resourceVersion: '3',
      },
      data: { storageState: 'AVAILABLE' },
    };
    const owned = {
      ...run,
      metadata: {
        ...run.metadata,
        labels: { 'pipelines.kubeflow.org/experiment': 'experiment-uid' },
      },
      status: { phase: 'Running' },
    };
    const archived = {
      ...owned,
      metadata: {
        ...owned.metadata,
        uid: 'sql-only',
        name: 'sql-only',
        resourceVersion: undefined,
      },
    };
    const schedule = {
      metadata: { name: 'schedule', uid: 'schedule-uid', namespace: 'team', resourceVersion: '2' },
      spec: {
        suspend: false,
        workflowMetadata: { labels: { 'pipelines.kubeflow.org/experiment': 'experiment-uid' } },
      },
    };
    const writes: Array<{ path: string; body: any }> = [];
    vi.stubGlobal(
      'fetch',
      vi.fn(async (path: string, options?: RequestInit) => {
        if (options?.method === 'PUT' || options?.method === 'POST') {
          const body = JSON.parse(String(options.body));
          writes.push({ path, body });
          return response(body);
        }
        if (path.includes('/configmaps/run-')) return response({}, 404);
        if (path.includes('/configmaps')) return response({ items: [] });
        if (path.includes('/cron-workflows/'))
          return response({
            items: [
              schedule,
              {
                ...schedule,
                metadata: { ...schedule.metadata, name: 'unrelated' },
                spec: {
                  ...schedule.spec,
                  workflowMetadata: { labels: { 'pipelines.kubeflow.org/experiment': 'other' } },
                },
              },
            ],
          });
        if (path.includes('/archived-workflows')) return response({ items: [archived] });
        return response({
          items: [
            ...(path.startsWith('/kubernetes/') ? [] : [archived]),
            owned,
            { ...run, metadata: { ...run.metadata, uid: 'other-uid' } },
            ...(writes.some(({ body }) => body.cronWorkflow)
              ? [{ ...owned, metadata: { ...owned.metadata, uid: 'late', name: 'late' } }]
              : []),
          ],
        });
      }),
    );
    await setExperimentStorage('team', experiment, 'ARCHIVED');
    expect(writes[0]).toMatchObject({
      path: '/argo/api/v1/cron-workflows/team/schedule',
      body: {
        cronWorkflow: {
          metadata: { uid: 'schedule-uid', resourceVersion: '2' },
          spec: { suspend: true },
        },
      },
    });
    expect(
      writes
        .filter(({ body }) => body.data?.runId)
        .map(({ body }) => body.data.runId)
        .sort(),
    ).toEqual(['late', 'live-uid', 'sql-only']);
    expect(writes.at(-1)).toMatchObject({
      body: {
        metadata: { uid: 'experiment-uid', resourceVersion: '3' },
        data: { storageState: 'ARCHIVED' },
      },
    });
    const count = writes.length;
    await setExperimentStorage('team', experiment, 'AVAILABLE');
    expect(writes).toHaveLength(count + 1);
    expect(writes.at(-1)?.body.data.storageState).toBe('AVAILABLE');
    expect(
      vi
        .mocked(fetch)
        .mock.calls.some(
          ([path, options]) => String(path).includes('/terminate') || options?.method === 'DELETE',
        ),
    ).toBe(false);
  });
  it.each(['listing', 'schedule', 'run-state'])(
    'does not publish experiment archival after a %s failure',
    async (phase) => {
      const experiment = {
        apiVersion: 'v1',
        kind: 'ConfigMap',
        metadata: {
          name: 'experiment-map',
          uid: 'experiment-uid',
          namespace: 'team',
          resourceVersion: '1',
        },
        data: { storageState: 'AVAILABLE' },
      };
      const owned = {
        ...run,
        metadata: {
          ...run.metadata,
          labels: { 'pipelines.kubeflow.org/experiment': 'experiment-uid' },
        },
      };
      const schedule = {
        metadata: {
          name: 'schedule',
          uid: 'schedule-uid',
          namespace: 'team',
          resourceVersion: '1',
        },
        spec: {
          workflowMetadata: { labels: { 'pipelines.kubeflow.org/experiment': 'experiment-uid' } },
        },
      };
      vi.stubGlobal(
        'fetch',
        vi.fn(async (path: string, options?: RequestInit) => {
          const method = options?.method || 'GET';
          if (
            (phase === 'listing' && path.includes('/api/v1/workflows/')) ||
            (phase === 'schedule' && method === 'PUT' && path.includes('/cron-workflows/')) ||
            (phase === 'run-state' && method === 'POST' && path.endsWith('/configmaps'))
          )
            return response({}, 403);
          if (method !== 'GET') return response({});
          if (path.includes('/cron-workflows/')) return response({ items: [schedule] });
          if (path.includes('/configmaps/run-')) return response({}, 404);
          if (path.includes('/api/v1/workflows/')) return response({ items: [owned] });
          return response({ items: [] });
        }),
      );
      await expect(setExperimentStorage('team', experiment, 'ARCHIVED')).rejects.toThrow('(403)');
      expect(
        vi
          .mocked(fetch)
          .mock.calls.some(
            ([path, options]) =>
              String(path).endsWith('/experiment-map') && options?.method === 'PUT',
          ),
      ).toBe(false);
      if (phase === 'listing')
        expect(
          vi
            .mocked(fetch)
            .mock.calls.every(([, options]) => !options?.method || options.method === 'GET'),
        ).toBe(true);
    },
  );
  it('requires restoring the experiment before restoring one of its runs', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        response({
          items: [
            {
              metadata: { name: 'experiment-map', uid: 'experiment-uid' },
              data: { storageState: 'ARCHIVED' },
            },
          ],
        }),
      ),
    );
    await expect(
      restoreRun({
        ...run,
        metadata: {
          ...run.metadata,
          labels: { 'pipelines.kubeflow.org/experiment': 'experiment-uid' },
        },
      }),
    ).rejects.toThrow('experiment first');
    expect(
      vi
        .mocked(fetch)
        .mock.calls.every(([, options]) => !options?.method || options.method === 'GET'),
    ).toBe(true);
  });
  it('orphans submitted runs when deleting a recurring run config', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => response({})),
    );
    await deleteNativeResource('team', {
      apiVersion: 'argoproj.io/v1alpha1',
      kind: 'CronWorkflow',
      metadata: { name: 'daily', uid: 'schedule-uid' },
    });
    expect(JSON.parse(String(vi.mocked(fetch).mock.calls[0][1]?.body))).toMatchObject({
      propagationPolicy: 'Orphan',
      preconditions: { uid: 'schedule-uid' },
    });
  });
  it('refuses to retry a reused name', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        response({ ...run, metadata: { ...run.metadata, uid: 'replacement-uid' } }),
      ),
    );
    await expect(retryRun(run)).rejects.toThrow('name was reused');
    expect(fetch).toHaveBeenCalledTimes(1);
  });
  it('reads only the selected task logs, using native pod identity annotations', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (path: string) =>
        path.startsWith('/kubernetes/')
          ? response({
              items: [
                {
                  metadata: {
                    name: 'wrong-pod',
                    annotations: { 'workflows.argoproj.io/node-id': 'wrong-node' },
                  },
                },
                {
                  metadata: {
                    name: 'right-pod',
                    annotations: { 'workflows.argoproj.io/node-id': 'right-node' },
                  },
                },
              ],
            })
          : new Response('{"result":{"content":"selected task output"}}\n'),
      ),
    );
    expect(await taskLogs(run, { id: 'right-node', displayName: 'train', type: 'Pod' })).toEqual([
      'selected task output',
    ]);
    expect(vi.mocked(fetch).mock.calls[1][0]).toContain('podName=right-pod');
  });
});
