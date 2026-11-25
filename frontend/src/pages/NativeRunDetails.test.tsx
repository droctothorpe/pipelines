// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Routes, Route, Link, useLocation } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { NativeUiContext, type Confirmation } from 'src/lib/NativeUiContext';
import { archiveRun, restoreRun, retryRun } from 'src/lib/NativeUi';
import { workflowAction } from 'src/lib/ArgoResources';
import NativeRunDetails from './NativeRunDetails';
import NativeExperimentDetails from './NativeExperimentDetails';
import { NativeCompare } from './NativeInspectors';

vi.mock('src/pages/v2/DagCanvas', () => ({
  default: ({ elements, onElementClick }: any) => (
    <div>
      {elements
        .filter((element: any) => element.data)
        .map((element: any) => (
          <button
            key={element.id}
            onClick={(event) => onElementClick(event, { layers: ['root'], element })}
          >
            {element.data.label}
          </button>
        ))}
    </div>
  ),
}));
vi.mock('src/components/LogViewer', () => ({
  default: ({ logLines }: { logLines: string[] }) => <pre>{logLines.join('\n')}</pre>,
}));
vi.mock('src/components/Editor', () => ({
  default: ({ value }: { value: string }) => <pre data-testid='editor'>{value}</pre>,
}));
vi.mock('src/lib/NativeUi', async (original) => ({
  ...(await original<typeof import('src/lib/NativeUi')>()),
  archiveRun: vi.fn(async () => undefined),
  restoreRun: vi.fn(async () => undefined),
  retryRun: vi.fn(async () => undefined),
}));
vi.mock('src/lib/ArgoResources', async (original) => ({
  ...(await original<typeof import('src/lib/ArgoResources')>()),
  workflowAction: vi.fn(async () => ({})),
}));
beforeEach(() => vi.clearAllMocks());

const run = {
  metadata: {
    name: 'run-one',
    namespace: 'argo',
    uid: 'uid-one',
    resourceVersion: '1',
    creationTimestamp: '2026-11-23T10:00:00Z',
    labels: { 'pipelines.kubeflow.org/experiment': 'training' },
    annotations: { 'pipelines.kubeflow.org/description': 'nightly training' },
  },
  spec: { arguments: { parameters: [{ name: 'epochs', value: '3' }] } },
  status: {
    phase: 'Succeeded',
    startedAt: '2026-11-23T10:00:05Z',
    finishedAt: '2026-11-23T10:04:05Z',
    nodes: {
      root: {
        id: 'run-one',
        name: 'run-one',
        displayName: 'run-one',
        type: 'DAG',
        children: ['prepare'],
      },
      prepare: {
        id: 'prepare',
        name: 'run-one.prepare',
        displayName: 'prepare',
        type: 'Pod',
        boundaryID: 'run-one',
        phase: 'Succeeded',
        startedAt: '2026-11-23T10:00:10Z',
        finishedAt: '2026-11-23T10:02:10Z',
        memoizationStatus: { hit: true },
        outputs: {
          artifacts: [{ name: 'kfp-metadata' }, { name: 'dataset' }],
          parameters: [
            { name: 'kfp-meta-dataset', value: '{"internal":true}' },
            { name: 'accuracy', value: '0.9' },
          ],
        },
      },
    },
  },
};
const extraNodes = {
  failing: {
    id: 'failing',
    name: 'run-one.failing',
    displayName: 'failing',
    type: 'Pod',
    boundaryID: 'run-one',
    phase: 'Failed',
    message: 'exit code 1',
    startedAt: '2026-11-23T10:02:10Z',
    finishedAt: '2026-11-23T10:03:10Z',
    outputs: { artifacts: [{ name: 'main-logs' }] },
  },
  gate: {
    id: 'gate',
    name: 'run-one.gate',
    displayName: 'gate',
    type: 'Suspend',
    boundaryID: 'run-one',
    phase: 'Running',
  },
  running: {
    id: 'running',
    name: 'run-one.running',
    displayName: 'running',
    type: 'Pod',
    boundaryID: 'run-one',
    phase: 'Running',
    startedAt: '2026-11-23T10:03:10Z',
  },
};
/** The stock run with the extra tasks attached below the root DAG. */
const withTasks = (phase: string, finished = true) => ({
  ...run,
  status: {
    ...run.status,
    phase,
    ...(finished ? {} : { finishedAt: undefined }),
    nodes: {
      ...run.status.nodes,
      root: { ...run.status.nodes.root, children: ['prepare', ...Object.keys(extraNodes)] },
      ...extraNodes,
    },
  },
});
const producer = { run: 'original-run', task: 'original-prepare', namespace: 'argo' };
const metadata = {
  schema: 'kfp-argo/v1',
  producer,
  inputs: [],
  metrics: { score: 0.75 },
  artifacts: [
    {
      port: 'dataset',
      type: 'system.Dataset@0.0.1',
      uri: 's3://bucket/original/dataset',
      producer,
      metadata: { rows: 4 },
    },
  ],
};
function Location() {
  const location = useLocation();
  return <span data-testid='location'>{location.pathname + location.search}</span>;
}
const clients: QueryClient[] = [];
function setup(
  path = '/runs/details/uid-one',
  otherRuns: unknown[] = [],
  options: { run?: typeof run; live?: boolean } = {},
) {
  const current = options.run || run;
  const live = options.live ?? true;
  const summary = live
    ? current
    : { ...current, metadata: { ...current.metadata, resourceVersion: undefined } };
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url.includes('/main-logs')) return new Response('line one\nline two\n');
      if (url.includes('/artifacts/')) return new Response(JSON.stringify(metadata));
      if (url.includes('/api/v1/workflows/argo/run-one'))
        return new Response(JSON.stringify(current));
      if (url.includes('/archived-workflows/uid-one')) return new Response(JSON.stringify(current));
      if (url.includes('/archived-workflows')) return new Response(JSON.stringify({ items: [] }));
      if (url.includes('/pods?')) return new Response(JSON.stringify({ items: [] }));
      if (url.includes('/configmaps') && !url.includes('resource%3Dexperiment'))
        return new Response(JSON.stringify({ items: [] }));
      if (url.includes('/configmaps'))
        return new Response(
          JSON.stringify({
            items: [
              {
                apiVersion: 'v1',
                kind: 'ConfigMap',
                metadata: { name: 'training', uid: 'experiment-uid', resourceVersion: '1' },
                data: { displayName: 'Human training', description: 'Training group' },
              },
            ],
          }),
        );
      if (url.includes('/workflow-templates') || url.includes('/cron-workflows'))
        return new Response(JSON.stringify({ items: [] }));
      if (url.startsWith('/kubernetes/apis/argoproj.io/'))
        return new Response(
          JSON.stringify({
            items: [...(live ? [current] : []), ...otherRuns].map((item: any) => ({
              metadata: item.metadata,
            })),
          }),
        );
      if (url.startsWith('/argo/api/v1/workflows/argo?'))
        return new Response(JSON.stringify({ items: [summary, ...otherRuns] }));
      throw new Error(`Unexpected request: ${url}`);
    }),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  clients.push(client);
  const confirm = vi.fn<(value: Confirmation) => void>();
  const fail = vi.fn();
  const view = render(
    <NativeUiContext.Provider value={{ namespace: 'argo', fail, confirm }}>
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path='/runs/details/:runId' element={<NativeRunDetails />} />
            <Route
              path='/experiments/details/:experimentId'
              element={<NativeExperimentDetails />}
            />
            <Route
              path='/compare'
              element={
                <>
                  <Link to='/compare?runlist=uid-one'>Compare selected</Link>
                  <NativeCompare />
                </>
              }
            />
            <Route path='*' element={null} />
          </Routes>
          <Location />
        </MemoryRouter>
      </QueryClientProvider>
    </NativeUiContext.Provider>,
  );
  return { client, confirm, fail, ...view };
}
afterEach(() => {
  cleanup();
  clients.splice(0).forEach((client) => client.clear());
  vi.unstubAllGlobals();
});
const button = (name: string) => screen.getByRole('button', { name, exact: true });
const location = () => screen.getByTestId('location').textContent;
async function click(name: string) {
  await act(async () => {
    fireEvent.click(button(name));
  });
}
const loaded = () => screen.findByRole('button', { name: 'prepare', exact: true });

describe('stock run presentation with native data', () => {
  it('filters experiment membership and displays the ConfigMap display name', async () => {
    setup('/experiments/details/training', [
      {
        ...run,
        metadata: {
          ...run.metadata,
          name: 'other-run',
          uid: 'other',
          labels: { 'pipelines.kubeflow.org/experiment': 'another' },
        },
      },
    ]);
    expect(await screen.findByText('Human training')).toBeInTheDocument();
    expect(await screen.findByRole('link', { name: 'run-one' })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'other-run' })).not.toBeInTheDocument();
  });
  it('opens an SDK experiment UID and keeps legacy membership visible', async () => {
    setup('/experiments/details/experiment-uid');
    expect(await screen.findByText('Human training')).toBeInTheDocument();
    expect(await screen.findByRole('link', { name: 'run-one' })).toBeInTheDocument();
  });
  it('retains the selected task across refresh and exposes cached artifact provenance', async () => {
    const { client } = setup();
    fireEvent.click(await loaded());
    expect(await screen.findByRole('link', { name: 'system.Dataset@0.0.1' })).toHaveAttribute(
      'href',
      '/artifacts/uid-one/prepare/dataset',
    );
    for (const name of ['Input/Output', 'Task Details', 'Logs']) {
      expect(screen.getByRole('button', { name, exact: true })).toBeInTheDocument();
    }
    expect(
      screen.queryByRole('button', { name: 'System Logs', exact: true }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText('kfp-meta-dataset')).not.toBeInTheDocument();
    expect(screen.queryByText('[object Object]')).not.toBeInTheDocument();
    await client.invalidateQueries({ queryKey: ['native', 'argo', 'run', 'uid-one'] });
    expect(screen.getByRole('link', { name: 'system.Dataset@0.0.1' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Logs', exact: true }));
    expect(screen.getByText(/reused cached outputs/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'dataset', exact: true }));
    expect(await screen.findByRole('link', { name: 'original-run', exact: true })).toHaveAttribute(
      'href',
      '/runs/details/original-run',
    );
    expect(screen.getByText('original-prepare')).toBeInTheDocument();
  });
  it('loads comparison data only for explicitly selected run identities', async () => {
    setup('/compare');
    expect(fetch).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('link', { name: 'Compare selected' }));
    expect(await screen.findByText('prepare / score')).toBeInTheDocument();
    expect(screen.getByText('0.75')).toBeInTheDocument();
  });
  it('shows denied refresh without falling back to KFP or discarding the graph', async () => {
    const { client } = setup();
    await loaded();
    vi.mocked(fetch).mockResolvedValue(new Response('{}', { status: 403 }));
    await client.invalidateQueries({ queryKey: ['native', 'argo', 'run', 'uid-one'] });
    await waitFor(() =>
      expect(screen.getByText(/Argo request failed \(403\)/)).toBeInTheDocument(),
    );
    expect(screen.getByRole('button', { name: 'prepare', exact: true })).toBeInTheDocument();
    expect(
      vi.mocked(fetch).mock.calls.every(([url]) => /^\/(argo|kubernetes)\//.test(String(url))),
    ).toBe(true);
  });
});

describe('page states', () => {
  it('shows a spinner while loading and the run title with the Runs breadcrumb afterwards', async () => {
    setup();
    expect(screen.getByLabelText('Loading run')).toBeInTheDocument();
    expect(screen.getByTestId('page-title')).toHaveTextContent('uid-one');
    await loaded();
    expect(screen.getByTestId('page-title')).toHaveTextContent('run-one');
    expect(screen.getByText('Runs')).toBeInTheDocument();
    expect(screen.queryByLabelText('Loading run')).toBeNull();
  });

  it('shows the error banner and placeholder when the run is missing', async () => {
    setup('/runs/details/unknown');
    expect(await screen.findByRole('alert')).toHaveTextContent('Run not found in this namespace.');
    expect(screen.getByText('Run data could not be loaded.')).toBeInTheDocument();
    expect(button('Clone run')).toBeDisabled();
    expect(button('Archive')).toBeDisabled();
  });

  it('refetches the run when Refresh is clicked', async () => {
    setup();
    await loaded();
    const before = vi
      .mocked(fetch)
      .mock.calls.filter(([url]) => String(url).includes('/api/v1/workflows/argo/run-one')).length;
    await click('Refresh');
    await waitFor(() =>
      expect(
        vi
          .mocked(fetch)
          .mock.calls.filter(([url]) => String(url).includes('/api/v1/workflows/argo/run-one'))
          .length,
      ).toBeGreaterThan(before),
    );
  });
});

describe('toolbar actions', () => {
  it('enables clone and archive but not retry or terminate for a succeeded live run', async () => {
    setup();
    await loaded();
    expect(button('Clone run')).toBeEnabled();
    expect(button('Archive')).toBeEnabled();
    expect(button('Retry')).toBeDisabled();
    expect(button('Terminate')).toBeDisabled();
  });

  it('enables terminate for a running run and confirms before stopping it', async () => {
    const { confirm } = setup(undefined, [], { run: withTasks('Running', false) });
    await loaded();
    expect(button('Terminate')).toBeEnabled();
    expect(button('Archive')).toBeDisabled();
    expect(button('Retry')).toBeDisabled();
    await click('Terminate');
    const confirmation = confirm.mock.calls[0][0];
    expect(confirmation.title).toBe('Terminate this run?');
    expect(vi.mocked(workflowAction)).not.toHaveBeenCalled();
    await act(async () => {
      await confirmation.action();
    });
    expect(vi.mocked(workflowAction)).toHaveBeenCalledWith(
      expect.objectContaining({ metadata: expect.objectContaining({ uid: 'uid-one' }) }),
      'terminate',
    );
  });

  it('retries a failed live run', async () => {
    setup(undefined, [], { run: withTasks('Failed') });
    await loaded();
    expect(button('Retry')).toBeEnabled();
    expect(button('Terminate')).toBeDisabled();
    await click('Retry');
    await waitFor(() => expect(vi.mocked(retryRun)).toHaveBeenCalledTimes(1));
    expect(vi.mocked(retryRun).mock.calls[0][0].metadata.uid).toBe('uid-one');
  });

  it('reports a failed retry through the UI error handler', async () => {
    vi.mocked(retryRun).mockRejectedValueOnce(new Error('name reused'));
    const { fail } = setup(undefined, [], { run: withTasks('Failed') });
    await loaded();
    await click('Retry');
    await waitFor(() => expect(fail).toHaveBeenCalledTimes(1));
    expect((fail.mock.calls[0][0] as Error).message).toBe('name reused');
  });

  it('archives a finished run after confirmation and moves to the archived list', async () => {
    const { confirm } = setup();
    await loaded();
    await click('Archive');
    const confirmation = confirm.mock.calls[0][0];
    expect(confirmation.title).toBe('Archive this run?');
    await act(async () => {
      await confirmation.action();
    });
    expect(vi.mocked(archiveRun)).toHaveBeenCalledTimes(1);
    expect(vi.mocked(archiveRun).mock.calls[0][0].metadata.uid).toBe('uid-one');
    expect(location()).toBe('/archive/runs');
  });

  it('offers Restore instead of Archive for an archived run and disables retry', async () => {
    const { confirm } = setup(undefined, [], { live: false });
    await loaded();
    expect(screen.queryByRole('button', { name: 'Archive' })).toBeNull();
    expect(button('Restore')).toBeEnabled();
    expect(button('Retry')).toBeDisabled();
    expect(button('Terminate')).toBeDisabled();
    expect(button('Clone run')).toBeEnabled();
    await click('Restore');
    const confirmation = confirm.mock.calls[0][0];
    expect(confirmation.title).toBe('Restore this run?');
    await act(async () => {
      await confirmation.action();
    });
    expect(vi.mocked(restoreRun)).toHaveBeenCalledTimes(1);
    expect(vi.mocked(archiveRun)).not.toHaveBeenCalled();
    expect(location()).toBe('/runs');
  });

  it('navigates to the clone form with this run preselected', async () => {
    setup();
    await loaded();
    await click('Clone run');
    expect(location()).toBe('/runs/new?cloneFromRun=uid-one');
  });
});

describe('tabs', () => {
  it('shows the run details and parameters on the Detail tab', async () => {
    setup();
    await loaded();
    await click('Detail');
    expect(screen.getByText('Run details')).toBeInTheDocument();
    for (const value of ['run-one', 'uid-one', 'SUCCEEDED', 'nightly training', 'argo'])
      expect(screen.getAllByText(value).length).toBeGreaterThan(0);
    expect(screen.getByText('Run parameters')).toBeInTheDocument();
    expect(screen.getByText('epochs')).toBeInTheDocument();
    expect(screen.getByText('3')).toBeInTheDocument();
  });

  it('shows the manifest on the Pipeline Spec tab', async () => {
    setup();
    await loaded();
    await click('Pipeline Spec');
    expect(screen.getByTestId('editor').textContent).toContain('name: epochs');
    expect(screen.getByTestId('editor').textContent).toContain("value: '3'");
  });

  it('opens the Timeline from the query string and keeps the URL in sync', async () => {
    setup('/runs/details/uid-one?tab=timeline');
    expect(await screen.findByRole('region', { name: 'Run timeline' })).toBeInTheDocument();
    expect(screen.getByRole('table', { name: 'Component timeline timings' })).toHaveTextContent(
      'prepare',
    );
    await click('Graph');
    expect(location()).toBe('/runs/details/uid-one');
    await click('Timeline');
    expect(location()).toBe('/runs/details/uid-one?tab=timeline');
  });

  it('opens the selected task in the graph from the Timeline inspector', async () => {
    setup('/runs/details/uid-one?tab=timeline');
    await screen.findByRole('region', { name: 'Run timeline' });
    await click('Open task in graph');
    expect(location()).toBe('/runs/details/uid-one?task=prepare');
    expect(await screen.findByRole('button', { name: 'Input/Output', exact: true })).toBeVisible();
    expect(screen.queryByRole('region', { name: 'Run timeline' })).toBeNull();
  });
});

describe('task side panel', () => {
  it('opens a deep-linked task and clears the link when the panel closes', async () => {
    setup('/runs/details/uid-one?task=prepare');
    expect(await screen.findByRole('button', { name: 'Task Details', exact: true })).toBeVisible();
    await click('close');
    expect(location()).toBe('/runs/details/uid-one');
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: 'Task Details', exact: true })).toBeNull(),
    );
  });

  it('lists output parameters, artifact downloads and metrics', async () => {
    setup();
    fireEvent.click(await loaded());
    await screen.findByRole('link', { name: 'system.Dataset@0.0.1' });
    expect(screen.getByText('accuracy')).toBeInTheDocument();
    expect(screen.getByText('0.9')).toBeInTheDocument();
    expect(screen.getByText('Metrics')).toBeInTheDocument();
    expect(screen.getByText('score')).toBeInTheDocument();
    expect(screen.getByText('0.75')).toBeInTheDocument();
    expect(button('Download')).toBeInTheDocument();
  });

  it('marks a memoized task as Cached on Task Details', async () => {
    setup();
    fireEvent.click(await loaded());
    await click('Task Details');
    expect(screen.getByText('Task details')).toBeInTheDocument();
    expect(screen.getByText('Cached')).toBeInTheDocument();
    expect(screen.getAllByText('prepare').length).toBeGreaterThan(0);
  });

  it('shows the failure message and archived logs for a failed task', async () => {
    setup(undefined, [], { run: withTasks('Failed') });
    await loaded();
    await click('failing');
    expect(await screen.findByRole('alert')).toHaveTextContent('exit code 1');
    await click('Logs');
    expect(await screen.findByText(/line one/)).toBeInTheDocument();
    expect(screen.getByTestId('log-status')).toHaveTextContent('Archived logs');
    expect(
      vi.mocked(fetch).mock.calls.some(([url]) => String(url).includes('/failing/main-logs')),
    ).toBe(true);
  });

  it('explains when a running task has no pod yet', async () => {
    setup(undefined, [], { run: withTasks('Running', false) });
    await loaded();
    await click('running');
    await click('Logs');
    expect(await screen.findByText('The task pod is not available yet.')).toBeInTheDocument();
  });

  it('resumes a suspended run from the task panel', async () => {
    setup(undefined, [], { run: withTasks('Running', false) });
    await loaded();
    await click('gate');
    expect(await screen.findByText('This run is waiting for approval.')).toBeInTheDocument();
    await click('Resume');
    await waitFor(() =>
      expect(vi.mocked(workflowAction)).toHaveBeenCalledWith(
        expect.objectContaining({ metadata: expect.objectContaining({ uid: 'uid-one' }) }),
        'resume',
      ),
    );
  });
});
