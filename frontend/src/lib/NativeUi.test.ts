// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  archiveRun,
  deleteNativeResource,
  getUiRun,
  listUiRuns,
  retryRun,
  taskLogs,
} from './NativeUi';
import { listResources } from './ArgoResources';
import type { ArgoWorkflow } from './Argo';
const run: ArgoWorkflow = {
  metadata: { name: 'same-name', namespace: 'team', uid: 'live-uid' },
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
          items: path.startsWith('/kubernetes/')
            ? [run]
            : [run, { ...run, metadata: { ...run.metadata, uid: 'older-uid' } }],
        }),
      ),
    );
    expect((await listUiRuns('team')).map((run) => [run.metadata.uid, run.live])).toEqual([
      ['live-uid', true],
      ['older-uid', false],
    ]);
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
    expect(fetch).toHaveBeenCalledTimes(4);
    expect(
      vi.mocked(fetch).mock.calls.filter(([url]) => String(url).includes('next%2B%2Fpage')),
    ).toHaveLength(2);
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
  it('fails visibly rather than looping forever on a repeated continuation token', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => response({ items: [], metadata: { continue: 'same' } })),
    );
    await expect(listUiRuns('team')).rejects.toThrow('repeated a pagination token');
  });
  it('never confuses a reused workflow name with an older run identity', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (path: string) =>
        response(
          path.includes('/same-name')
            ? { ...run, metadata: { ...run.metadata, uid: 'replacement-uid' } }
            : path.startsWith('/kubernetes/')
              ? { items: [run] }
              : { items: [] },
        ),
      ),
    );
    await expect(getUiRun('team', 'live-uid')).rejects.toThrow('name was reused');
  });
  it('verifies durable archival before deleting a live workflow with a UID precondition', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => response(run)),
    );
    await archiveRun(run);
    expect(vi.mocked(fetch).mock.calls[0][0]).toContain(
      '/archived-workflows/live-uid?namespace=team',
    );
    const [url, options] = vi.mocked(fetch).mock.calls[1];
    expect(url).toBe('/kubernetes/apis/argoproj.io/v1alpha1/namespaces/team/workflows/same-name');
    expect(options?.method).toBe('DELETE');
    expect(JSON.parse(String(options?.body)).preconditions).toEqual({ uid: 'live-uid' });
  });
  it.each([403, 404])(
    'does not delete a workflow when archive verification returns %s',
    async (status) => {
      vi.stubGlobal(
        'fetch',
        vi.fn(async () => response({}, status)),
      );
      await expect(archiveRun(run)).rejects.toThrow(`(${status})`);
      expect(fetch).toHaveBeenCalledTimes(1);
    },
  );
  it('does not delete a running workflow through Archive', async () => {
    vi.stubGlobal('fetch', vi.fn());
    await expect(archiveRun({ ...run, status: { phase: 'Running' } })).rejects.toThrow(
      'Only completed runs',
    );
    expect(fetch).not.toHaveBeenCalled();
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
