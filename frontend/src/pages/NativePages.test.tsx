// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { NativeUiContext, type Confirmation } from 'src/lib/NativeUiContext';
import { SCHEDULE_CONFIG } from 'src/lib/NativeScheduling';
import {
  EXPERIMENT,
  PIPELINE,
  archiveRun,
  deleteArchivedRun,
  deleteNativeResource,
  restoreRun,
} from 'src/lib/NativeUi';
import { VERSION_NAME } from 'src/lib/NativeImport';
import { NativeListPage, NativePipelineDetails } from './NativePages';

const mocks = vi.hoisted(() => ({ inventory: undefined as any }));
vi.mock('src/lib/NativeQueries', () => ({
  useInventory: () => mocks.inventory,
  useArtifactInventory: () => ({ isPending: false, data: [] }),
}));
vi.mock('src/lib/NativeUi', async (original) => ({
  ...(await original<typeof import('src/lib/NativeUi')>()),
  archiveRun: vi.fn(async () => undefined),
  restoreRun: vi.fn(async () => undefined),
  deleteArchivedRun: vi.fn(async () => undefined),
  deleteNativeResource: vi.fn(async () => undefined),
}));
vi.mock('src/components/Editor', () => ({
  default: ({ value }: { value: string }) => <pre data-testid='editor'>{value}</pre>,
}));
vi.mock('src/components/graph/PipelineGraph', () => ({
  default: ({ elements, selection, onSelectionChange, renderDetails, children }: any) => (
    <div>
      {elements
        .filter((element: any) => element.data)
        .map((element: any) => (
          <button key={element.id} onClick={() => onSelectionChange({ layers: ['root'], element })}>
            {element.data.label}
          </button>
        ))}
      {selection && renderDetails(selection)}
      {children}
    </div>
  ),
}));
vi.mock('src/components/navigators/PipelineVersionCard', () => ({
  PipelineVersionCard: ({ selectedVersion, versions, handleVersionSelected }: any) => (
    <div>
      <span data-testid='selected-version'>{selectedVersion?.display_name}</span>
      {versions.map((version: any) => (
        <button
          key={version.pipeline_version_id}
          onClick={() => handleVersionSelected(version.pipeline_version_id)}
        >
          Switch to {version.display_name}
        </button>
      ))}
    </div>
  ),
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
const pipeline = (name: string, uid: string, data: Record<string, string> = {}) => ({
  apiVersion: 'v1',
  kind: 'ConfigMap',
  metadata: { name, uid, namespace: 'team', creationTimestamp: '2026-11-20T10:00:00Z' },
  data: { displayName: name.toUpperCase(), ...data },
});
const version = (
  name: string,
  pipelineUid: string,
  created = '2026-11-23T10:00:00Z',
  spec: Record<string, unknown> = {},
) => ({
  apiVersion: 'argoproj.io/v1alpha1',
  kind: 'WorkflowTemplate',
  metadata: {
    name,
    uid: `uid-${name}`,
    namespace: 'team',
    creationTimestamp: created,
    labels: { [PIPELINE]: pipelineUid },
    annotations: { [VERSION_NAME]: `${name} display` },
  },
  spec,
});
const run = (
  name: string,
  phase: string,
  options: {
    uid?: string;
    created?: string;
    experiment?: string;
    version?: string;
    schedule?: string;
    live?: boolean;
    storageState?: string;
  } = {},
) => ({
  apiVersion: 'argoproj.io/v1alpha1',
  kind: 'Workflow',
  metadata: {
    name,
    uid: options.uid || `uid-${name}`,
    namespace: 'team',
    creationTimestamp: options.created || '2026-11-23T10:00:00Z',
    labels: {
      ...(options.experiment ? { [EXPERIMENT]: options.experiment } : {}),
      ...(options.schedule ? { 'workflows.argoproj.io/cron-workflow': options.schedule } : {}),
    },
  },
  spec: options.version ? { workflowTemplateRef: { name: options.version } } : {},
  status: {
    phase,
    startedAt: options.created || '2026-11-23T10:00:00Z',
    ...(['Succeeded', 'Failed', 'Error'].includes(phase)
      ? { finishedAt: '2026-11-23T10:05:00Z' }
      : {}),
  },
  live: options.live ?? true,
  storageState: options.storageState || 'AVAILABLE',
});
const schedule = (name: string, suspend: boolean, config?: Record<string, unknown>) => ({
  apiVersion: 'argoproj.io/v1alpha1',
  kind: 'CronWorkflow',
  metadata: {
    name,
    uid: `cron-${name}`,
    namespace: 'team',
    creationTimestamp: '2026-11-23T10:00:00Z',
    annotations: config ? { [SCHEDULE_CONFIG]: JSON.stringify(config) } : {},
  },
  spec: {
    schedules: ['0 2 * * *'],
    suspend,
    startingDeadlineSeconds: 0,
    workflowMetadata: { labels: { [EXPERIMENT]: 'exp-id' } },
  },
});

function Location() {
  const location = useLocation();
  return <span data-testid='location'>{location.pathname + location.search}</span>;
}

type Kind = 'schedules' | 'pipelines' | 'runs' | 'experiments';
function setup(
  kind: Kind | 'pipeline-details',
  inventory: Record<string, unknown[]>,
  options: {
    archived?: boolean;
    shared?: boolean;
    route?: string;
    pending?: boolean;
    error?: unknown;
  } = {},
) {
  mocks.inventory = {
    pending: options.pending ?? false,
    error: options.error,
    experiments: query([experiment]),
    runs: query([]),
    schedules: query([]),
    versions: query([]),
    pipelines: query([]),
    ...Object.fromEntries(Object.entries(inventory).map(([key, data]) => [key, query(data)])),
  };
  if (options.pending) mocks.inventory.versions.isPending = true;
  const confirm = vi.fn<(value: Confirmation) => void>();
  const fail = vi.fn();
  const page =
    kind === 'pipeline-details' ? (
      <NativePipelineDetails />
    ) : (
      <NativeListPage kind={kind} archived={options.archived} shared={options.shared} />
    );
  render(
    <NativeUiContext.Provider value={{ namespace: 'team', fail, confirm }}>
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter initialEntries={[options.route || `/${kind}`]}>
          <Routes>
            <Route path='/pipelines/details/:pipelineId' element={page} />
            <Route path='/pipelines/details/:pipelineId/version/:versionId' element={page} />
            <Route path='*' element={page} />
          </Routes>
          <Location />
        </MemoryRouter>
      </QueryClientProvider>
    </NativeUiContext.Provider>,
  );
  return { confirm, fail };
}

const location = () => screen.getByTestId('location').textContent;
const button = (name: string) => screen.getByRole('button', { name });
const rowIds = () =>
  Array.from(document.querySelectorAll('[data-row-id]')).map((row) =>
    row.getAttribute('data-row-id'),
  );
async function selectRow(id: string) {
  const row = document.querySelector(`[data-row-id="${id}"]`)!;
  await act(async () => {
    fireEvent.click(row.querySelector('input[type=checkbox], input[type=radio]')!);
  });
}
async function click(name: string) {
  await act(async () => {
    fireEvent.click(button(name));
  });
}

it('shows the schedule window and links the experiment on the recurring run list (C31, C36)', () => {
  const start = '2026-12-01T02:00:00.000Z';
  const end = '2026-12-31T02:00:00.000Z';
  setup('schedules', {
    schedules: [
      schedule('nightly', false, {
        max_concurrency: 1,
        no_catchup: true,
        trigger: { kind: 'cron', cron: '0 2 * * *', start_time: start, end_time: end },
      }),
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
  const { confirm } = setup('pipelines', {
    pipelines: [pipeline('pipe', 'pipe-1')],
    versions: [version('v1', 'pipe-1'), version('v2', 'pipe-1')],
  });
  const row = document.querySelector('[data-row-id="pipe-1"]')!;
  await act(async () => {
    fireEvent.click(within(row as HTMLElement).getAllByRole('button')[0]);
  });
  await selectRow('v2');
  await click('Delete');
  expect(confirm).toHaveBeenCalledTimes(1);
  expect(confirm.mock.calls[0][0].title).toBe('Delete 0 pipeline(s) and 1 pipeline version(s)?');
});

describe('run list', () => {
  it('renders the empty experience for active and archived runs', async () => {
    setup('runs', {});
    expect(await screen.findByText('No available runs found.')).toBeInTheDocument();
    cleanup();
    setup('runs', { runs: [run('done', 'Succeeded')] }, { archived: true });
    expect(await screen.findByText('No available runs found.')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'done' })).not.toBeInTheDocument();
  });

  it('links the run, its experiment, pipeline version and recurring run', () => {
    setup('runs', {
      runs: [
        run('train', 'Succeeded', { experiment: 'exp-id', version: 'v1', schedule: 'nightly' }),
      ],
      versions: [version('v1', 'pipe-1')],
    });
    expect(screen.getByRole('link', { name: 'train' })).toHaveAttribute(
      'href',
      '/runs/details/uid-train',
    );
    expect(screen.getByRole('link', { name: 'Training' })).toHaveAttribute(
      'href',
      '/experiments/details/exp-id',
    );
    expect(screen.getByRole('link', { name: 'v1 display' })).toHaveAttribute(
      'href',
      '/pipelines/details/pipe-1/version/uid-v1',
    );
    expect(screen.getByRole('link', { name: 'nightly' })).toHaveAttribute(
      'href',
      '/recurringrun/details/nightly',
    );
  });

  it('falls back to the template name and dashes when references are missing', () => {
    setup('runs', { runs: [run('orphan', 'Running', { version: 'gone' })] });
    const row = document.querySelector('[data-row-id="uid-orphan"]')!;
    expect(row.textContent).toContain('gone');
    expect(within(row as HTMLElement).queryByRole('link', { name: 'gone' })).toBeNull();
    expect(row.textContent).toContain('-');
  });

  it('shows pending runs with a status icon and a dash duration', () => {
    setup('runs', { runs: [run('waiting', 'Pending')] });
    const row = document.querySelector('[data-row-id="uid-waiting"]')!;
    expect(row.textContent).toContain('-');
    expect(row.querySelector('svg')).not.toBeNull();
  });

  it('enables compare from two selections and clone for exactly one', async () => {
    const runs = Array.from({ length: 3 }, (_, i) =>
      run(`run-${i}`, 'Succeeded', { created: `2026-11-2${i}T10:00:00Z` }),
    );
    setup('runs', { runs });
    expect(button('Create run')).toBeEnabled();
    expect(button('Compare runs')).toBeDisabled();
    expect(button('Clone run')).toBeDisabled();
    expect(button('Archive')).toBeDisabled();
    await selectRow('uid-run-0');
    expect(button('Clone run')).toBeEnabled();
    expect(button('Compare runs')).toBeDisabled();
    expect(button('Archive')).toBeEnabled();
    await selectRow('uid-run-1');
    expect(button('Clone run')).toBeDisabled();
    expect(button('Compare runs')).toBeEnabled();
    await selectRow('uid-run-2');
    expect(button('Compare runs')).toBeEnabled();
    expect(button('Clone run')).toBeDisabled();
  });

  it('disables archive while an unfinished run is selected', async () => {
    setup('runs', { runs: [run('done', 'Succeeded'), run('busy', 'Running')] });
    await selectRow('uid-done');
    expect(button('Archive')).toBeEnabled();
    await selectRow('uid-busy');
    expect(button('Archive')).toBeDisabled();
  });

  it('navigates to the clone, compare and create pages with the selected ids', async () => {
    setup('runs', { runs: [run('a', 'Succeeded'), run('b', 'Failed')] });
    await selectRow('uid-a');
    await click('Clone run');
    expect(location()).toBe('/runs/new?cloneFromRun=uid-a');
    cleanup();
    setup('runs', { runs: [run('a', 'Succeeded'), run('b', 'Failed')] });
    await selectRow('uid-a');
    await selectRow('uid-b');
    await click('Compare runs');
    expect(location()).toBe('/compare?runlist=uid-a,uid-b');
    cleanup();
    setup('runs', {});
    await click('Create run');
    expect(location()).toBe('/runs/new');
  });

  it('archives the selected runs after confirmation and clears the selection', async () => {
    const runs = [run('a', 'Succeeded'), run('b', 'Failed')];
    const { confirm } = setup('runs', { runs });
    await selectRow('uid-a');
    await selectRow('uid-b');
    await click('Archive');
    const confirmation = confirm.mock.calls[0][0];
    expect(confirmation.title).toBe('Archive 2 run(s)?');
    await act(async () => {
      await confirmation.action();
    });
    expect(vi.mocked(archiveRun)).toHaveBeenCalledTimes(2);
    expect(vi.mocked(archiveRun).mock.calls.map(([entry]) => entry.metadata.name)).toEqual([
      'a',
      'b',
    ]);
    expect(button('Archive')).toBeDisabled();
  });

  it('offers restore and permanent delete on the archived list', async () => {
    const archived = run('old', 'Succeeded', { live: false, storageState: 'ARCHIVED' });
    const { confirm } = setup(
      'runs',
      { runs: [archived, run('fresh', 'Succeeded')] },
      { archived: true },
    );
    expect(screen.getByRole('link', { name: 'old' })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'fresh' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Archive' })).toBeNull();
    expect(button('Restore')).toBeDisabled();
    expect(button('Delete')).toBeDisabled();
    await selectRow('uid-old');
    await click('Delete');
    expect(confirm.mock.calls[0][0].title).toBe('Delete 1 run(s)?');
    await act(async () => {
      await confirm.mock.calls[0][0].action();
    });
    expect(vi.mocked(deleteArchivedRun).mock.calls.map(([entry]) => entry)).toEqual([archived]);
    await selectRow('uid-old');
    await click('Restore');
    expect(vi.mocked(restoreRun).mock.calls.map(([entry]) => entry)).toEqual([archived]);
  });

  it('switches between the Active and Archived tabs by route', async () => {
    setup('runs', {});
    await click('Archived');
    expect(location()).toBe('/archive/runs');
    cleanup();
    setup('runs', {}, { archived: true, route: '/archive/runs' });
    await click('Active');
    expect(location()).toBe('/runs');
  });

  it('filters rows by name and sorts by the Run name column', async () => {
    setup('runs', {
      runs: [
        run('alpha', 'Succeeded', { created: '2026-11-21T10:00:00Z' }),
        run('beta', 'Succeeded', { created: '2026-11-22T10:00:00Z' }),
        run('gamma', 'Succeeded', { created: '2026-11-23T10:00:00Z' }),
      ],
    });
    expect(rowIds()).toEqual(['uid-gamma', 'uid-beta', 'uid-alpha']);
    await act(async () => {
      fireEvent.click(screen.getByText('Run name'));
    });
    await waitFor(() => expect(rowIds()).toEqual(['uid-alpha', 'uid-beta', 'uid-gamma']));
    fireEvent.change(screen.getByLabelText('Filter runs'), { target: { value: 'ALPH' } });
    await waitFor(() => expect(rowIds()).toEqual(['uid-alpha']));
  });

  it('paginates ten rows per page', async () => {
    const runs = Array.from({ length: 12 }, (_, i) =>
      run(`run-${String(i).padStart(2, '0')}`, 'Succeeded', {
        created: `2026-11-${String(i + 1).padStart(2, '0')}T10:00:00Z`,
      }),
    );
    setup('runs', { runs });
    expect(rowIds()).toHaveLength(10);
    expect(screen.queryByRole('link', { name: 'run-00' })).toBeNull();
    await waitFor(() => expect(screen.getByRole('button', { name: 'Next page' })).toBeEnabled());
    await click('Next page');
    expect(await screen.findByRole('link', { name: 'run-00' })).toBeInTheDocument();
    expect(rowIds()).toHaveLength(2);
  });

  it('shows the inventory error banner and the loading state', () => {
    setup('runs', {}, { error: new Error('Argo request failed (403)') });
    expect(screen.getByRole('alert')).toHaveTextContent('Argo request failed (403)');
    cleanup();
    setup('runs', {}, { pending: true });
    expect(screen.getByLabelText('Loading')).toBeInTheDocument();
    expect(screen.queryByText('No available runs found.')).toBeNull();
  });
});

describe('experiment list', () => {
  it('renders the empty experiences', async () => {
    setup('experiments', { experiments: [] });
    expect(
      await screen.findByText('No experiments found. Click "Create experiment" to start.'),
    ).toBeInTheDocument();
    cleanup();
    setup('experiments', { experiments: [experiment] }, { archived: true });
    expect(await screen.findByText('No archived experiments found.')).toBeInTheDocument();
    expect(screen.queryByText('Last 5 runs')).toBeNull();
  });

  it('links each experiment and shows its five newest active runs as status links', () => {
    const runs = Array.from({ length: 7 }, (_, i) =>
      run(`run-${i}`, 'Succeeded', { experiment: 'exp-id', created: `2026-11-1${i}T10:00:00Z` }),
    );
    runs.push(
      run('archived', 'Succeeded', {
        experiment: 'exp-id',
        live: false,
        storageState: 'ARCHIVED',
        created: '2026-11-30T10:00:00Z',
      }),
    );
    setup('experiments', {
      experiments: [{ ...experiment, data: { ...experiment.data, description: 'Nightly jobs' } }],
      runs,
    });
    expect(screen.getByRole('link', { name: 'Training' })).toHaveAttribute(
      'href',
      '/experiments/details/exp-id',
    );
    expect(screen.getByText('Nightly jobs')).toBeInTheDocument();
    const row = document.querySelector('[data-row-id="exp-id"]')!;
    const links = within(row as HTMLElement)
      .getAllByRole('link')
      .filter((link) => link.getAttribute('href')?.startsWith('/runs/details/'));
    expect(links.map((link) => link.getAttribute('title'))).toEqual([
      'run-6',
      'run-5',
      'run-4',
      'run-3',
      'run-2',
    ]);
  });

  it('expands an experiment to list its runs without the Experiment column', async () => {
    setup('experiments', {
      runs: [run('mine', 'Succeeded', { experiment: 'exp-id' }), run('other', 'Succeeded')],
    });
    const row = document.querySelector('[data-row-id="exp-id"]')!;
    await act(async () => {
      fireEvent.click(within(row as HTMLElement).getByRole('button', { name: 'Expand' }));
    });
    expect(screen.getByRole('link', { name: 'mine' })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'other' })).toBeNull();
    expect(screen.queryByText('Experiment', { selector: '[title="Experiment"]' })).toBeNull();
  });

  it('acts on runs selected inside expanded experiments', async () => {
    const { confirm } = setup('experiments', {
      runs: [
        run('one', 'Succeeded', { experiment: 'exp-id' }),
        run('two', 'Failed', { experiment: 'exp-id', created: '2026-11-22T10:00:00Z' }),
      ],
    });
    expect(button('Create experiment')).toBeEnabled();
    expect(button('Clone run')).toBeDisabled();
    expect(button('Compare runs')).toBeDisabled();
    const row = document.querySelector('[data-row-id="exp-id"]')!;
    await act(async () => {
      fireEvent.click(within(row as HTMLElement).getByRole('button', { name: 'Expand' }));
    });
    await selectRow('uid-one');
    expect(button('Clone run')).toBeEnabled();
    await selectRow('uid-two');
    expect(button('Compare runs')).toBeEnabled();
    await click('Archive');
    expect(confirm.mock.calls[0][0].title).toBe('Archive 2 run(s)?');
    await click('Compare runs');
    expect(location()).toBe('/compare?runlist=uid-one,uid-two');
  });

  it('navigates to the new experiment page', async () => {
    setup('experiments', {});
    await click('Create experiment');
    expect(location()).toBe('/experiments/new');
  });
});

describe('recurring run list', () => {
  it('renders the empty experience and the create action', async () => {
    setup('schedules', {});
    expect(await screen.findByText('No available recurring runs found.')).toBeInTheDocument();
    await click('Create recurring run');
    expect(location()).toBe('/runs/new?recurring=1');
  });

  it('shows enabled and suspended schedules with their cron trigger and missing window', () => {
    setup('schedules', {
      schedules: [schedule('nightly', false), schedule('paused', true)],
    });
    const nightly = document.querySelector('[data-row-id="nightly"]')!;
    expect(nightly.textContent).toContain('Enabled');
    expect(nightly.textContent).toContain('Scheduled');
    expect(nightly.textContent).toContain('0 2 * * *');
    const paused = document.querySelector('[data-row-id="paused"]')!;
    expect(paused.textContent).toContain('Disabled');
    expect(paused.textContent).toContain('Suspended');
    expect(screen.getByRole('link', { name: 'nightly' })).toHaveAttribute(
      'href',
      '/recurringrun/details/nightly',
    );
  });

  it('shows the periodic interval of an @every schedule', () => {
    const periodic = schedule('hourly', false);
    periodic.spec.schedules = ['@every 3600s'];
    setup('schedules', { schedules: [periodic] });
    expect(document.querySelector('[data-row-id="hourly"]')!.textContent).toContain('@every 3600s');
  });
});

describe('pipeline list', () => {
  it('renders the empty experience and the upload action', async () => {
    setup('pipelines', {});
    expect(
      await screen.findByText('No pipelines found. Click "Upload pipeline" to start.'),
    ).toBeInTheDocument();
    expect(button('Upload pipeline')).toBeEnabled();
    await click('Upload pipeline');
    expect(location()).toBe('/pipeline_versions/new');
  });

  it('links each pipeline to its newest version and shows its description', () => {
    setup('pipelines', {
      pipelines: [pipeline('pipe', 'pipe-1', { description: 'Trains a model' })],
      versions: [
        version('old', 'pipe-1', '2026-11-01T10:00:00Z'),
        version('new', 'pipe-1', '2026-11-23T10:00:00Z'),
      ],
    });
    expect(screen.getByRole('link', { name: 'PIPE' })).toHaveAttribute(
      'href',
      '/pipelines/details/pipe-1/version/uid-new',
    );
    expect(screen.getByText('Trains a model')).toBeInTheDocument();
  });

  it('lists a pipeline that has versions but no ConfigMap record', () => {
    setup('pipelines', { versions: [version('solo', 'pipe-x')] });
    expect(screen.getByRole('link', { name: 'solo' })).toHaveAttribute(
      'href',
      '/pipelines/details/pipe-x/version/uid-solo',
    );
  });

  it('shows only shared pipelines on the shared list', () => {
    setup(
      'pipelines',
      {
        pipelines: [pipeline('mine', 'p-1'), pipeline('shared', 'p-2', { shared: 'true' })],
      },
      { shared: true },
    );
    expect(screen.getByRole('link', { name: 'SHARED' })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'MINE' })).toBeNull();
  });

  it('enables delete with a selection and deletes versions before the pipeline record', async () => {
    const record = pipeline('pipe', 'pipe-1');
    const versions = [version('v1', 'pipe-1'), version('v2', 'pipe-1', '2026-11-24T10:00:00Z')];
    const { confirm } = setup('pipelines', {
      pipelines: [record, pipeline('other', 'pipe-2')],
      versions,
    });
    expect(button('Delete')).toBeDisabled();
    await selectRow('pipe-1');
    expect(button('Delete')).toBeEnabled();
    await selectRow('pipe-2');
    await click('Delete');
    expect(confirm.mock.calls[0][0].title).toBe('Delete 2 pipeline(s)?');
    await act(async () => {
      await confirm.mock.calls[0][0].action();
    });
    const deleted = vi
      .mocked(deleteNativeResource)
      .mock.calls.map(([, entry]) => entry.metadata.name);
    expect(deleted).toEqual(expect.arrayContaining(['v1', 'v2', 'pipe', 'other']));
    expect(deleted.indexOf('pipe')).toBeGreaterThan(
      Math.max(deleted.indexOf('v1'), deleted.indexOf('v2')),
    );
    expect(button('Delete')).toBeDisabled();
  });

  it('re-disables delete when the pipeline is unselected', async () => {
    setup('pipelines', { pipelines: [pipeline('pipe', 'pipe-1')] });
    await selectRow('pipe-1');
    expect(button('Delete')).toBeEnabled();
    await selectRow('pipe-1');
    expect(button('Delete')).toBeDisabled();
  });

  it('keeps namespace transfer visible but unavailable in the More actions menu', async () => {
    setup('pipelines', {});
    await click('More actions');
    const item = await screen.findByRole('menuitem', { name: /Import \/ export namespace data/ });
    expect(item).toHaveAttribute('aria-disabled', 'true');
  });
});

describe('pipeline details', () => {
  const versions = [
    version('v1', 'pipe-1', '2026-11-01T10:00:00Z', {
      entrypoint: 'root',
      templates: [
        { name: 'root', dag: { tasks: [{ name: 'prepare', template: 'prepare' }] } },
        { name: 'prepare', container: { image: 'old-image', command: ['python'] } },
      ],
    }),
    version('v2', 'pipe-1', '2026-11-23T10:00:00Z', {
      entrypoint: 'root',
      templates: [
        { name: 'root', dag: { tasks: [{ name: 'train', template: 'train' }] } },
        { name: 'train', container: { image: 'new-image', args: ['--epochs', '3'] } },
      ],
    }),
  ];
  const details = (route = '/pipelines/details/pipe-1') =>
    setup('pipeline-details', { pipelines: [pipeline('pipe', 'pipe-1')], versions }, { route });

  it('shows the newest version by default with the pipeline breadcrumb', () => {
    details();
    expect(screen.getByTestId('page-title')).toHaveTextContent('v2 (v2 display)');
    expect(screen.getByTestId('selected-version')).toHaveTextContent('v2 display');
    expect(screen.getByText('Pipelines')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'train' })).toBeInTheDocument();
  });

  it('shows the version named in the URL and switches versions through the card', async () => {
    details('/pipelines/details/pipe-1/version/uid-v1');
    expect(screen.getByTestId('selected-version')).toHaveTextContent('v1 display');
    expect(screen.getByRole('button', { name: 'prepare' })).toBeInTheDocument();
    await click('Switch to v2 display');
    expect(location()).toBe('/pipelines/details/pipe-1/version/v2');
    expect(screen.getByRole('button', { name: 'train' })).toBeInTheDocument();
  });

  it('shows task details for a selected graph node', async () => {
    details();
    await click('train');
    expect(screen.getByText('Task details')).toBeInTheDocument();
    expect(screen.getByText('new-image')).toBeInTheDocument();
    expect(
      screen.getAllByTestId('editor').some((editor) => editor.textContent?.includes('--epochs')),
    ).toBe(true);
  });

  it('navigates to create a run, upload a version and create an experiment', async () => {
    details();
    await click('Create run');
    expect(location()).toBe('/runs/new?pipelineVersionId=v2');
    cleanup();
    details();
    await click('Upload version');
    expect(location()).toBe('/pipeline_versions/new?pipelineId=pipe-1');
    cleanup();
    details();
    await click('Create experiment');
    expect(location()).toBe('/experiments/new?pipelineId=pipe-1');
  });

  it('deletes the shown version after confirmation and returns to the list', async () => {
    const { confirm } = details('/pipelines/details/pipe-1/version/uid-v1');
    expect(button('Delete')).toBeEnabled();
    await click('Delete');
    expect(confirm.mock.calls[0][0].title).toBe('Delete this pipeline version?');
    await act(async () => {
      await confirm.mock.calls[0][0].action();
    });
    expect(vi.mocked(deleteNativeResource)).toHaveBeenCalledWith('team', versions[0]);
    expect(mocks.inventory.versions.refetch).toHaveBeenCalledTimes(1);
    expect(location()).toBe('/pipelines');
  });

  it('disables run and delete when the version is unavailable', () => {
    details('/pipelines/details/pipe-1/version/missing');
    expect(screen.getByText('The selected pipeline version is unavailable.')).toBeInTheDocument();
    expect(button('Create run')).toBeDisabled();
    expect(button('Delete')).toBeDisabled();
    expect(button('Upload version')).toBeEnabled();
  });

  it('shows the loading text while versions are pending', () => {
    setup('pipeline-details', {}, { route: '/pipelines/details/pipe-1', pending: true });
    expect(screen.getByText('Loading pipeline…')).toBeInTheDocument();
  });

  it('renders the manifest YAML on the Pipeline Spec tab', async () => {
    details();
    await click('Pipeline Spec');
    expect(screen.getByTestId('editor').textContent).toContain('name: v2');
    expect(screen.getByTestId('editor').textContent).toContain('image: new-image');
  });

  it('shows an error banner when the manifest references a missing template', () => {
    setup(
      'pipeline-details',
      {
        versions: [
          version('broken', 'pipe-1', '2026-11-23T10:00:00Z', {
            entrypoint: 'root',
            templates: [{ name: 'root', dag: { tasks: [{ name: 'x', template: 'absent' }] } }],
          }),
        ],
      },
      { route: '/pipelines/details/pipe-1' },
    );
    expect(screen.getByRole('alert')).toHaveTextContent('Missing native template absent.');
  });
});
