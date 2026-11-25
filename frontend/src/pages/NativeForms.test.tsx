// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { NativeUiContext } from 'src/lib/NativeUiContext';
import { SCHEDULE_CONFIG, createSchedule } from 'src/lib/NativeScheduling';
import { createResource, submitRun } from 'src/lib/ArgoResources';
import { ARTIFACT_ROOT, bindArtifactRoot } from 'src/lib/NativeArtifacts';
import { DESCRIPTION, DISPLAY_NAME, EXPERIMENT, PIPELINE, getUiRun } from 'src/lib/NativeUi';
import { VERSION_NAME } from 'src/lib/NativeImport';
import { NativeNewExperiment, NativeNewRun } from './NativeForms';

const mocks = vi.hoisted(() => ({ inventory: undefined as any }));
vi.mock('src/lib/NativeQueries', () => ({ useInventory: () => mocks.inventory }));
vi.mock('src/lib/ArgoResources', async (original) => ({
  ...(await original<typeof import('src/lib/ArgoResources')>()),
  createResource: vi.fn(),
  submitRun: vi.fn(),
}));
vi.mock('src/lib/NativeScheduling', async (original) => ({
  ...(await original<typeof import('src/lib/NativeScheduling')>()),
  createSchedule: vi.fn(async () => ({})),
}));
vi.mock('src/lib/NativeArtifacts', async (original) => ({
  ...(await original<typeof import('src/lib/NativeArtifacts')>()),
  bindArtifactRoot: vi.fn(async () => ({ annotations: {}, spec: {} })),
}));
vi.mock('src/lib/NativeUi', async (original) => ({
  ...(await original<typeof import('src/lib/NativeUi')>()),
  getUiRun: vi.fn(),
}));
afterEach(cleanup);
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(submitRun).mockResolvedValue({ metadata: { uid: 'new-run', name: 'wf' } });
  vi.mocked(createResource).mockImplementation(async (_namespace, _kind, resource: any) => ({
    ...resource,
    metadata: { ...resource.metadata, uid: `uid-${resource.metadata.name}` },
  }));
});

const VERSION_ID = 'pipelines.kubeflow.org/version-id';
const TYPES = 'pipelines.kubeflow.org/parameter-types';
const version = (
  name: string,
  pipelineUid: string,
  created: string,
  options: {
    parameters?: Array<{ name: string; value?: string }>;
    types?: Record<string, string>;
    root?: string;
    serviceAccount?: string;
  } = {},
) => ({
  apiVersion: 'argoproj.io/v1alpha1',
  kind: 'WorkflowTemplate',
  metadata: {
    name,
    uid: `uid-${name}`,
    namespace: 'team',
    creationTimestamp: created,
    labels: { [PIPELINE]: pipelineUid },
    annotations: {
      [VERSION_NAME]: `${name} display`,
      ...(options.types ? { [TYPES]: JSON.stringify(options.types) } : {}),
      ...(options.root ? { [ARTIFACT_ROOT]: options.root } : {}),
    },
  },
  spec: {
    ...(options.serviceAccount ? { serviceAccountName: options.serviceAccount } : {}),
    arguments: { parameters: options.parameters || [] },
  },
});
const trainer = version('trainer-v2', 'pipe-1', '2026-11-23T10:00:00Z', {
  parameters: [{ name: 'epochs', value: '3' }, { name: 'dataset' }],
  types: { epochs: 'Integer', dataset: 'String' },
});
const trainerOld = version('trainer-v1', 'pipe-1', '2026-11-01T10:00:00Z', {
  parameters: [{ name: 'epochs', value: '1' }],
  types: { epochs: 'Integer' },
});
const plain = version('plain-v1', 'pipe-2', '2026-11-10T10:00:00Z', {
  root: 's3://bucket/default-root',
  serviceAccount: 'pipeline-runner',
});
const nullable = version('nullable-v1', 'pipe-3', '2026-11-11T10:00:00Z', {
  parameters: [{ name: 'note', value: 'null' }],
  types: { note: 'NullableString' },
});
const configMap = (name: string, uid: string, displayName: string) => ({
  apiVersion: 'v1',
  kind: 'ConfigMap',
  metadata: { name, uid, namespace: 'team', creationTimestamp: '2026-11-01T10:00:00Z' },
  data: { displayName, description: `${displayName} description` },
});
const training = configMap('experiment-a', 'exp-id', 'Training');
const clonedRun = {
  metadata: {
    name: 'trainer-v2-abc',
    uid: 'run-1',
    namespace: 'team',
    labels: { [VERSION_ID]: 'uid-trainer-v2', [EXPERIMENT]: 'exp-id' },
    annotations: {
      [DISPLAY_NAME]: 'Original run',
      [DESCRIPTION]: 'first attempt',
      'pipelines.kubeflow.org/pipeline-root': 's3://bucket/custom',
    },
  },
  spec: {
    serviceAccountName: 'runner',
    arguments: {
      parameters: [
        { name: 'epochs', value: '7' },
        { name: 'dataset', value: 'gs://d' },
      ],
    },
  },
  live: true,
};
const clonedSchedule = {
  apiVersion: 'argoproj.io/v1alpha1',
  kind: 'CronWorkflow',
  metadata: {
    name: 'schedule-123',
    uid: 'cron-1',
    namespace: 'team',
    labels: { [VERSION_ID]: 'uid-trainer-v2' },
    annotations: {
      [DISPLAY_NAME]: 'Nightly',
      [DESCRIPTION]: 'every night',
      [SCHEDULE_CONFIG]: JSON.stringify({
        max_concurrency: 2,
        no_catchup: true,
        trigger: { kind: 'periodic', interval_second: 600 },
      }),
    },
  },
  spec: {
    schedules: ['@every 600s'],
    suspend: false,
    workflowMetadata: { labels: { [EXPERIMENT]: 'exp-id' } },
    workflowSpec: {
      serviceAccountName: 'nightly-runner',
      arguments: {
        parameters: [
          { name: 'epochs', value: '9' },
          { name: 'dataset', value: 'x' },
        ],
      },
    },
  },
};

function Location() {
  const location = useLocation();
  return <span data-testid='location'>{location.pathname + location.search}</span>;
}
function setup(
  route = '/runs/new',
  inventory: Record<string, unknown[]> = {},
  options: { error?: unknown; page?: 'run' | 'experiment' } = {},
) {
  const query = (data: unknown[]) => ({ data, refetch: vi.fn(async () => ({})) });
  mocks.inventory = {
    pending: false,
    error: options.error,
    experiments: query([training]),
    runs: query([]),
    schedules: query([]),
    versions: query([trainer, trainerOld, plain, nullable]),
    pipelines: query([
      configMap('pipe', 'pipe-1', 'Trainer'),
      configMap('plain', 'pipe-2', 'Plain'),
      configMap('nullable', 'pipe-3', 'Nullable'),
    ]),
    ...Object.fromEntries(Object.entries(inventory).map(([key, data]) => [key, query(data)])),
  };
  const fail = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <NativeUiContext.Provider value={{ namespace: 'team', fail, confirm: vi.fn() }}>
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[route]}>
          <Routes>
            <Route path='/experiments/new' element={<NativeNewExperiment />} />
            <Route path='*' element={<NativeNewRun />} />
          </Routes>
          <Location />
        </MemoryRouter>
      </QueryClientProvider>
    </NativeUiContext.Provider>,
  );
  return { fail };
}

const location = () => screen.getByTestId('location').textContent;
const field = (name: string | RegExp) => screen.getByRole('textbox', { name }) as HTMLInputElement;
const start = () => screen.getByRole('button', { name: 'Start' });
const chooser = (index: 0 | 1 | 2) => screen.getAllByRole('button', { name: 'Choose' })[index];
async function click(element: Element) {
  await act(async () => {
    fireEvent.click(element);
  });
}
const closed = () => waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
async function pick(id: string) {
  const dialog = screen.getByRole('dialog');
  await click(dialog.querySelector(`[data-row-id="${id}"]`)!);
  await click(within(dialog).getByRole('button', { name: /^Use this/ }));
  await closed();
}

describe('new run form', () => {
  it('starts empty: no parameters, disabled version chooser and disabled Start', () => {
    setup();
    expect(screen.getByTestId('page-title')).toHaveTextContent('Start a new run');
    expect(field('Pipeline').value).toBe('');
    expect(chooser(1)).toBeDisabled();
    expect(screen.getByText('Parameters will appear after you select a pipeline')).toBeVisible();
    expect(start()).toBeDisabled();
    expect(screen.queryByText('Run trigger')).toBeNull();
  });

  it('preselects the version from the query and derives the run name and defaults', () => {
    setup('/runs/new?pipelineVersionId=trainer-v2&experimentId=exp-id');
    expect(field('Pipeline').value).toBe('trainer-v2');
    expect(field('Pipeline Version').value).toBe('trainer-v2');
    expect(field('Run name').value).toBe('Run of trainer-v2');
    expect(field('Experiment').value).toBe('Training');
    expect(field('epochs').value).toBe('3');
    expect(field('dataset').value).toBe('');
    expect(screen.getByText('Specify parameters required by the pipeline')).toBeVisible();
  });

  it('selects the newest version of a pipeline given only a pipeline id', () => {
    setup('/runs/new?pipelineId=pipe-1');
    expect(field('Pipeline Version').value).toBe('trainer-v2');
    cleanup();
    setup('/runs/new?pipelineVersionId=plain-v1');
    expect(screen.getByText('This pipeline has no parameters')).toBeVisible();
    expect(field('Service Account').value).toBe('pipeline-runner');
  });

  it('disables Start until a required parameter without a default is filled', async () => {
    setup('/runs/new?pipelineVersionId=trainer-v2');
    expect(start()).toBeDisabled();
    fireEvent.change(field('dataset'), { target: { value: 'gs://data' } });
    expect(start()).toBeEnabled();
    fireEvent.change(field('Run name'), { target: { value: '   ' } });
    expect(start()).toBeDisabled();
  });

  it('chooses a pipeline from the dialog, listing one entry per pipeline', async () => {
    setup();
    await click(chooser(0));
    const dialog = screen.getByRole('dialog');
    expect(within(dialog).getByText('Choose a pipeline')).toBeVisible();
    const rows = Array.from(dialog.querySelectorAll('[data-row-id]')).map((row) =>
      row.getAttribute('data-row-id')!,
    );
    expect(rows).toHaveLength(3);
    expect(within(dialog).getByRole('button', { name: 'Use this pipeline' })).toBeDisabled();
    const chosen = rows.find((row) => row.startsWith('trainer-'))!;
    await pick(chosen);
    expect(field('Pipeline').value).toBe(chosen);
    expect(field('Run name').value).toBe(`Run of ${chosen}`);
    expect(chooser(1)).toBeEnabled();
  });

  it('offers each pipeline through its newest version, whatever the inventory order', async () => {
    // U49: stock defaults a chosen pipeline to its latest version.
    setup();
    await click(chooser(0));
    const dialog = screen.getByRole('dialog');
    const rows = Array.from(dialog.querySelectorAll('[data-row-id]')).map((row) =>
      row.getAttribute('data-row-id')!,
    );
    expect(rows.filter((row) => row.startsWith('trainer-'))).toEqual(['trainer-v2']);
    cleanup();
    setup('/runs/new', { versions: [trainerOld, trainer, plain, nullable] });
    await click(chooser(0));
    const reordered = Array.from(screen.getByRole('dialog').querySelectorAll('[data-row-id]')).map(
      (row) => row.getAttribute('data-row-id')!,
    );
    expect(reordered.filter((row) => row.startsWith('trainer-'))).toEqual(['trainer-v2']);
  });

  it('lists only the selected pipeline versions and resets edited parameters on switch', async () => {
    setup('/runs/new?pipelineVersionId=trainer-v2');
    fireEvent.change(field('epochs'), { target: { value: '42' } });
    await click(chooser(1));
    const dialog = screen.getByRole('dialog');
    expect(within(dialog).getByText('Choose a pipeline version')).toBeVisible();
    expect(
      Array.from(dialog.querySelectorAll('[data-row-id]')).map((row) =>
        row.getAttribute('data-row-id'),
      ),
    ).toEqual(['trainer-v2', 'trainer-v1']);
    await pick('trainer-v1');
    expect(field('Pipeline Version').value).toBe('trainer-v1');
    expect(field('epochs').value).toBe('1');
    expect(field('Run name').value).toBe('Run of trainer-v1');
  });

  it('keeps a custom run name when the version changes', async () => {
    setup('/runs/new?pipelineVersionId=trainer-v2');
    fireEvent.change(field('Run name'), { target: { value: 'my run' } });
    await click(chooser(1));
    await pick('trainer-v1');
    expect(field('Run name').value).toBe('my run');
  });

  it('chooses an experiment and offers to create one from the dialog', async () => {
    setup('/runs/new', { experiments: [training, configMap('b', 'exp-b', 'Benchmarks')] });
    await click(chooser(2));
    const dialog = screen.getByRole('dialog');
    expect(within(dialog).getByText('Choose an experiment')).toBeVisible();
    expect(within(dialog).getByText('Benchmarks description')).toBeVisible();
    await pick('b');
    expect(field('Experiment').value).toBe('Benchmarks');
    await click(chooser(2));
    await click(
      within(screen.getByRole('dialog')).getByRole('button', { name: 'Create new experiment' }),
    );
    expect(location()).toBe('/experiments/new');
  });

  it('cancels the dialog without changing the selection', async () => {
    setup('/runs/new?pipelineVersionId=trainer-v2');
    await click(chooser(1));
    await click(screen.getByRole('dialog').querySelector('[data-row-id="trainer-v1"]')!);
    await click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Cancel' }));
    await closed();
    expect(field('Pipeline Version').value).toBe('trainer-v2');
  });

  it('submits the run with the edited parameters, description and service account', async () => {
    setup('/runs/new?pipelineVersionId=trainer-v2&experimentId=exp-id');
    fireEvent.change(field('dataset'), { target: { value: 'gs://data' } });
    fireEvent.change(field('epochs'), { target: { value: '5' } });
    fireEvent.change(field('Description'), { target: { value: 'tuning' } });
    fireEvent.change(field('Service Account'), { target: { value: 'sa' } });
    await click(start());
    await waitFor(() => expect(location()).toBe('/runs/details/new-run'));
    expect(vi.mocked(submitRun)).toHaveBeenCalledWith(
      'team',
      trainer,
      { epochs: '5', dataset: 'gs://data' },
      'exp-id',
      'Run of trainer-v2',
      'tuning',
      'sa',
      undefined,
    );
    expect(vi.mocked(createResource)).not.toHaveBeenCalled();
  });

  it('falls back to the existing Default experiment when none is chosen', async () => {
    setup('/runs/new?pipelineVersionId=plain-v1', {
      experiments: [training, configMap('default-cm', 'default-id', 'Default')],
    });
    expect(field('Experiment').value).toBe('');
    await click(start());
    await waitFor(() => expect(vi.mocked(submitRun)).toHaveBeenCalled());
    expect(vi.mocked(submitRun).mock.calls[0][3]).toBe('default-id');
    expect(vi.mocked(createResource)).not.toHaveBeenCalled();
  });

  it('creates the Default experiment on first use', async () => {
    setup('/runs/new?pipelineVersionId=plain-v1', { experiments: [] });
    await click(start());
    await waitFor(() => expect(vi.mocked(submitRun)).toHaveBeenCalled());
    const [, kind, created] = vi.mocked(createResource).mock.calls[0];
    expect(kind).toBe('experiments');
    expect(created.data?.displayName).toBe('Default');
    expect(vi.mocked(submitRun).mock.calls[0][3]).toBe(`uid-${created.metadata.name}`);
  });

  it('requires a value for a custom pipeline root and passes it on', async () => {
    setup('/runs/new?pipelineVersionId=plain-v1');
    expect(screen.queryByRole('textbox', { name: 'Pipeline Root' })).toBeNull();
    await click(screen.getByLabelText('Custom Pipeline Root'));
    expect(field('Pipeline Root').value).toBe('s3://bucket/default-root');
    fireEvent.change(field('Pipeline Root'), { target: { value: '  ' } });
    expect(start()).toBeDisabled();
    fireEvent.change(field('Pipeline Root'), { target: { value: 's3://bucket/mine' } });
    expect(start()).toBeEnabled();
    await click(start());
    await waitFor(() => expect(vi.mocked(submitRun)).toHaveBeenCalled());
    expect(vi.mocked(submitRun).mock.calls[0][7]).toBe('s3://bucket/mine');
  });

  it('reports a failed submission and re-enables Start', async () => {
    vi.mocked(submitRun).mockRejectedValueOnce(new Error('forbidden'));
    const { fail } = setup('/runs/new?pipelineVersionId=plain-v1');
    await click(start());
    await waitFor(() => expect(fail).toHaveBeenCalledWith(expect.any(Error)));
    expect((fail.mock.calls[0][0] as Error).message).toBe('forbidden');
    expect(start()).toBeEnabled();
    expect(location()).toBe('/runs/new?pipelineVersionId=plain-v1');
  });

  it('returns to the run list on Cancel', async () => {
    setup();
    await click(screen.getByRole('button', { name: 'Cancel' }));
    expect(location()).toBe('/runs');
  });

  it('renders nullable parameters with the None toggle', () => {
    setup('/runs/new?pipelineVersionId=nullable-v1');
    expect(screen.getByRole('checkbox', { name: 'Use None for note' })).toBeChecked();
    expect(field('note')).toBeDisabled();
    expect(start()).toBeEnabled();
  });

  it('shows the inventory error banner', () => {
    setup('/runs/new', {}, { error: new Error('Argo request failed (503)') });
    expect(screen.getByRole('alert')).toHaveTextContent('Argo request failed (503)');
  });
});

describe('recurring runs', () => {
  it('switches to a recurring run with the trigger section and pinned version note', async () => {
    setup('/runs/new?pipelineVersionId=plain-v1');
    await click(screen.getByLabelText('Recurring'));
    expect(screen.getByTestId('page-title')).toHaveTextContent('Start a recurring run');
    expect(screen.getByText('Run trigger')).toBeVisible();
    expect(field('Recurring run config name').value).toBe('Run of plain-v1');
    expect(screen.getByLabelText('Always use the latest pipeline version')).toBeDisabled();
    await click(screen.getByLabelText('One-off'));
    expect(screen.queryByText('Run trigger')).toBeNull();
  });

  it('opens directly in recurring mode from the recurring list', () => {
    setup('/runs/new?recurring=1');
    expect(screen.getByText('Run trigger')).toBeVisible();
    expect(screen.getByLabelText('Recurring')).toBeChecked();
  });

  it('submits an hourly schedule with the default concurrency and lands on its details', async () => {
    setup('/runs/new?pipelineVersionId=trainer-v2&experimentId=exp-id&recurring=1');
    fireEvent.change(field('dataset'), { target: { value: 'gs://data' } });
    await waitFor(() => expect(start()).toBeEnabled());
    await click(start());
    await waitFor(() => expect(vi.mocked(createSchedule)).toHaveBeenCalledTimes(1));
    const [namespace, resource, settings] = vi.mocked(createSchedule).mock.calls[0];
    expect(namespace).toBe('team');
    expect(resource.kind).toBe('CronWorkflow');
    expect(resource.metadata.annotations?.[DISPLAY_NAME]).toBe('Run of trainer-v2');
    expect(resource.metadata.labels?.[VERSION_ID]).toBe('uid-trainer-v2');
    expect(resource.spec.workflowMetadata.labels[EXPERIMENT]).toBe('exp-id');
    expect(resource.spec.workflowSpec.arguments.parameters).toEqual([
      { name: 'epochs', value: '3' },
      { name: 'dataset', value: 'gs://data' },
    ]);
    expect(settings.maxConcurrentRuns).toBe('10');
    expect(settings.trigger?.periodic_schedule?.interval_second).toBe('3600');
    expect(location()).toBe(`/recurringrun/details/${resource.metadata.name}`);
    expect(vi.mocked(bindArtifactRoot)).toHaveBeenCalledWith('team', trainer, undefined);
    expect(vi.mocked(submitRun)).not.toHaveBeenCalled();
  });

  it('passes edited trigger settings through', async () => {
    setup('/runs/new?pipelineVersionId=plain-v1&recurring=1');
    fireEvent.change(field('Maximum concurrent runs'), { target: { value: '5' } });
    fireEvent.change(screen.getByDisplayValue('1'), { target: { value: '15' } });
    await click(screen.getByLabelText('Catchup'));
    await click(start());
    await waitFor(() => expect(vi.mocked(createSchedule)).toHaveBeenCalledTimes(1));
    const settings = vi.mocked(createSchedule).mock.calls[0][2];
    expect(settings.maxConcurrentRuns).toBe('5');
    expect(settings.catchup).toBe(false);
    expect(settings.trigger?.periodic_schedule?.interval_second).toBe(String(15 * 3600));
  });

  it.each(['10a', '-10', '0'])('disables Start for an invalid concurrency %s', async (value) => {
    setup('/runs/new?pipelineVersionId=plain-v1&recurring=1');
    await waitFor(() => expect(start()).toBeEnabled());
    fireEvent.change(field('Maximum concurrent runs'), { target: { value } });
    await waitFor(() => expect(start()).toBeDisabled());
  });
});

describe('cloning', () => {
  it('prefills a cloned run from the original and submits it', async () => {
    vi.mocked(getUiRun).mockResolvedValue(clonedRun as any);
    setup('/runs/new?cloneFromRun=run-1');
    expect(screen.getByTestId('page-title')).toHaveTextContent('Clone a run');
    await waitFor(() => expect(field('Run name').value).toBe('Clone of Original run'));
    expect(vi.mocked(getUiRun)).toHaveBeenCalledWith('team', 'run-1', expect.anything());
    expect(field('Pipeline Version').value).toBe('trainer-v2');
    expect(field('Experiment').value).toBe('Training');
    expect(field('Description').value).toBe('first attempt');
    expect(field('Service Account').value).toBe('runner');
    expect(field('epochs').value).toBe('7');
    expect(field('dataset').value).toBe('gs://d');
    expect(screen.getByLabelText('Custom Pipeline Root')).toBeChecked();
    expect(field('Pipeline Root').value).toBe('s3://bucket/custom');
    await click(start());
    await waitFor(() => expect(vi.mocked(submitRun)).toHaveBeenCalledTimes(1));
    expect(vi.mocked(submitRun).mock.calls[0].slice(2)).toEqual([
      { epochs: '7', dataset: 'gs://d' },
      'exp-id',
      'Clone of Original run',
      'first attempt',
      'runner',
      's3://bucket/custom',
    ]);
  });

  it('lets the user edit cloned parameters before starting', async () => {
    vi.mocked(getUiRun).mockResolvedValue(clonedRun as any);
    setup('/runs/new?cloneFromRun=run-1');
    await waitFor(() => expect(field('epochs').value).toBe('7'));
    fireEvent.change(field('epochs'), { target: { value: '8' } });
    await click(start());
    await waitFor(() => expect(vi.mocked(submitRun)).toHaveBeenCalledTimes(1));
    expect(vi.mocked(submitRun).mock.calls[0][2]).toEqual({ epochs: '8', dataset: 'gs://d' });
  });

  it('shows the error banner when the original run cannot be loaded', async () => {
    vi.mocked(getUiRun).mockRejectedValue(new Error('Run not found in this namespace.'));
    setup('/runs/new?cloneFromRun=missing');
    expect(await screen.findByRole('alert')).toHaveTextContent('Run not found in this namespace.');
    expect(start()).toBeDisabled();
  });

  it('clones a recurring run with its trigger, concurrency and parameters', async () => {
    setup('/runs/new?cloneFromRecurringRun=schedule-123', { schedules: [clonedSchedule] });
    expect(screen.getByTestId('page-title')).toHaveTextContent('Clone a recurring run');
    expect(screen.getByLabelText('Recurring')).not.toBeChecked();
    expect(field('Run name').value).toBe('Clone of Nightly');
    expect(field('Pipeline Version').value).toBe('trainer-v2');
    expect(field('Experiment').value).toBe('Training');
    expect(field('Description').value).toBe('every night');
    expect(field('Service Account').value).toBe('nightly-runner');
    expect(field('epochs').value).toBe('9');
    await click(screen.getByLabelText('Recurring'));
    expect(field('Maximum concurrent runs').value).toBe('2');
    expect(screen.getByLabelText('Catchup')).not.toBeChecked();
    await waitFor(() => expect(start()).toBeEnabled());
    await click(start());
    await waitFor(() => expect(vi.mocked(createSchedule)).toHaveBeenCalledTimes(1));
    const [, resource, settings] = vi.mocked(createSchedule).mock.calls[0];
    expect(settings.maxConcurrentRuns).toBe('2');
    expect(settings.catchup).toBe(false);
    expect(settings.trigger?.periodic_schedule?.interval_second).toBe('600');
    expect(resource.spec.workflowSpec.serviceAccountName).toBe('nightly-runner');
    expect(resource.spec.workflowSpec.arguments.parameters).toEqual([
      { name: 'epochs', value: '9' },
      { name: 'dataset', value: 'x' },
    ]);
    expect(resource.metadata.annotations?.[DISPLAY_NAME]).toBe('Clone of Nightly');
  });
});

describe('new experiment form', () => {
  it('requires a name before Next and cancels back to the list', async () => {
    setup('/experiments/new');
    const next = screen.getByRole('button', { name: 'Next' });
    expect(next).toBeDisabled();
    expect(screen.getByText('Experiment name is required')).toBeVisible();
    fireEvent.change(field('Experiment name'), { target: { value: '  ' } });
    expect(next).toBeDisabled();
    fireEvent.change(field('Experiment name'), { target: { value: 'Benchmarks' } });
    expect(next).toBeEnabled();
    expect(screen.queryByText('Experiment name is required')).toBeNull();
    await click(screen.getByRole('button', { name: 'Cancel' }));
    expect(location()).toBe('/experiments');
  });

  it('creates the experiment ConfigMap and continues to the first run', async () => {
    setup('/experiments/new?pipelineId=pipe-1');
    fireEvent.change(field('Experiment name'), { target: { value: ' Benchmarks ' } });
    fireEvent.change(field('Description'), { target: { value: 'weekly' } });
    await click(screen.getByRole('button', { name: 'Next' }));
    await waitFor(() => expect(vi.mocked(createResource)).toHaveBeenCalledTimes(1));
    const [namespace, kind, resource] = vi.mocked(createResource).mock.calls[0];
    expect(namespace).toBe('team');
    expect(kind).toBe('experiments');
    expect(resource.metadata.labels).toEqual({ 'pipelines.kubeflow.org/resource': 'experiment' });
    expect(resource.data).toEqual({
      displayName: 'Benchmarks',
      description: 'weekly',
      storageState: 'AVAILABLE',
    });
    await waitFor(() =>
      expect(location()).toBe(
        `/runs/new?experimentId=uid-${resource.metadata.name}&firstRunInExperiment=1&pipelineId=pipe-1`,
      ),
    );
  });

  it('reports a failed creation and stays on the form', async () => {
    vi.mocked(createResource).mockRejectedValueOnce(new Error('denied'));
    const { fail } = setup('/experiments/new');
    fireEvent.change(field('Experiment name'), { target: { value: 'Benchmarks' } });
    await click(screen.getByRole('button', { name: 'Next' }));
    await waitFor(() => expect(fail).toHaveBeenCalledTimes(1));
    expect(location()).toBe('/experiments/new');
    expect(screen.getByRole('button', { name: 'Next' })).toBeEnabled();
  });
});
