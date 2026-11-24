// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import { cleanup, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { NativeUiContext, type Confirmation } from 'src/lib/NativeUiContext';
import { SCHEDULE_CONFIG } from 'src/lib/NativeScheduling';
import { PIPELINE } from 'src/lib/NativeUi';
import { VERSION_NAME } from 'src/lib/NativeImport';
import { fireEvent, act } from '@testing-library/react';
import { NativeListPage } from './NativePages';

const mocks = vi.hoisted(() => ({ inventory: undefined as any }));
vi.mock('src/lib/NativeQueries', () => ({
  useInventory: () => mocks.inventory,
  useArtifactInventory: () => ({ isPending: false, data: [] }),
}));
afterEach(cleanup);
beforeEach(() => vi.clearAllMocks());

const query = (data: unknown[]) => ({ data, refetch: vi.fn(async () => ({})) });
const experiment = {
  apiVersion: 'v1',
  kind: 'ConfigMap',
  metadata: { name: 'experiment', uid: 'exp-id', namespace: 'team' },
  data: { displayName: 'Training', storageState: 'AVAILABLE' },
};

function setup(kind: 'schedules' | 'pipelines', inventory: Record<string, unknown[]>) {
  mocks.inventory = {
    pending: false,
    experiments: query([experiment]),
    runs: query([]),
    schedules: query([]),
    versions: query([]),
    pipelines: query([]),
    ...Object.fromEntries(Object.entries(inventory).map(([key, data]) => [key, query(data)])),
  };
  const confirm = vi.fn<(value: Confirmation) => void>();
  render(
    <NativeUiContext.Provider value={{ namespace: 'team', fail: vi.fn(), confirm }}>
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
          <NativeListPage kind={kind} />
        </MemoryRouter>
      </QueryClientProvider>
    </NativeUiContext.Provider>,
  );
  return { confirm };
}

it('shows the schedule window and links the experiment on the recurring run list (C31, C36)', () => {
  const start = '2026-12-01T02:00:00.000Z';
  const end = '2026-12-31T02:00:00.000Z';
  setup('schedules', {
    schedules: [
      {
        apiVersion: 'argoproj.io/v1alpha1',
        kind: 'CronWorkflow',
        metadata: {
          name: 'nightly',
          uid: 'cron-1',
          namespace: 'team',
          creationTimestamp: '2026-11-23T10:00:00Z',
          annotations: {
            [SCHEDULE_CONFIG]: JSON.stringify({
              max_concurrency: 1,
              no_catchup: true,
              trigger: { kind: 'cron', cron: '0 2 * * *', start_time: start, end_time: end },
            }),
          },
        },
        spec: {
          schedules: ['0 2 * * *'],
          suspend: false,
          startingDeadlineSeconds: 0,
          workflowMetadata: { labels: { 'pipelines.kubeflow.org/experiment': 'exp-id' } },
        },
      },
    ],
  });
  const row = screen.getByRole('link', { name: 'nightly' }).closest('[role="row"], tr, div')!;
  const text = row.parentElement?.textContent || '';
  expect(text).toContain(new Date(start).toLocaleString());
  expect(text).toContain(new Date(end).toLocaleString());
  const experimentLink = screen.getByRole('link', { name: 'Training' });
  expect(experimentLink.getAttribute('href')).toBe('/experiments/details/exp-id');
});

it('deletes pipeline versions selected inside an expanded row, as stock allowed (C36)', async () => {
  const version = (name: string) => ({
    apiVersion: 'argoproj.io/v1alpha1',
    kind: 'WorkflowTemplate',
    metadata: {
      name,
      uid: `uid-${name}`,
      namespace: 'team',
      creationTimestamp: '2026-11-23T10:00:00Z',
      labels: { [PIPELINE]: 'pipe-1' },
      annotations: { [VERSION_NAME]: name },
    },
    spec: {},
  });
  const { confirm } = setup('pipelines', {
    pipelines: [
      {
        apiVersion: 'v1',
        kind: 'ConfigMap',
        metadata: { name: 'pipe', uid: 'pipe-1', namespace: 'team' },
        data: { displayName: 'Pipe' },
      },
    ],
    versions: [version('v1'), version('v2')],
  });
  const row = document.querySelector('[data-row-id="pipe-1"]')!;
  await act(async () => {
    fireEvent.click(within(row as HTMLElement).getAllByRole('button')[0]);
  });
  const versionRow = document.querySelector('[data-row-id="v2"]')!;
  await act(async () => {
    fireEvent.click(versionRow.querySelector('input[type=checkbox]')!);
  });
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));
  });
  expect(confirm).toHaveBeenCalledTimes(1);
  expect(confirm.mock.calls[0][0].title).toBe('Delete 0 pipeline(s) and 1 pipeline version(s)?');
});
