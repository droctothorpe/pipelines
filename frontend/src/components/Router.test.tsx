// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import { useEffect, useState } from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { useLocation, useParams } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { setArgoToken } from 'src/lib/Argo';
import Router, { ExternalLinks, RoutePage, RoutePrefix } from './Router';

// The pages are heavy data-bound components; the router is tested with
// lightweight stand-ins that expose what the router hands them.
const mounts = vi.hoisted(() => ({ runDetails: 0 }));

vi.mock('src/pages/NativePages', async () => {
  const { useNativeUi } = await import('src/lib/NativeUiContext');
  // Stands in for any page that reports failures or asks for confirmation.
  const Compare = () => {
    const { fail, confirm } = useNativeUi();
    return (
      <div>
        <div>Compare</div>
        <button onClick={() => fail(new Error('Current load error'))}>Fail loading</button>
        <button
          onClick={() =>
            confirm({
              title: 'Delete run?',
              content: 'This cannot be undone.',
              action: async () => {
                throw new Error('denied');
              },
            })
          }
        >
          Delete
        </button>
      </div>
    );
  };
  const Stateful = ({ label }: { label: string }) => {
    const [selection, setSelection] = useState('initial');
    return (
      <div>
        <div>{label}</div>
        <button onClick={() => setSelection('selected')}>{`${label}:${selection}`}</button>
      </div>
    );
  };
  return {
    NativeListPage: ({
      kind,
      archived,
      shared,
    }: {
      kind: string;
      archived?: boolean;
      shared?: boolean;
    }) => (
      <Stateful label={`list:${kind}${archived ? ':archived' : ''}${shared ? ':shared' : ''}`} />
    ),
    NativePipelineDetails: () => <output>{JSON.stringify(useParams())}</output>,
    NativeExperimentDetails: () => <output>{JSON.stringify(useParams())}</output>,
    NativeNewExperiment: () => <div>New experiment</div>,
    NativeNewRun: () => {
      const location = useLocation();
      const [name, setName] = useState(new URLSearchParams(location.search).get('name') || '');
      return (
        <input aria-label='Name' value={name} onChange={(event) => setName(event.target.value)} />
      );
    },
    NativeCompare: Compare,
    NativeArtifactDetails: () => <output>{JSON.stringify(useParams())}</output>,
    NativeScheduleDetails: () => <output>{JSON.stringify(useParams())}</output>,
  };
});

vi.mock('src/pages/NativeRunDetails', () => {
  const RunDetails = () => {
    const params = useParams();
    const location = useLocation();
    const [selection, setSelection] = useState('initial');
    useEffect(() => {
      mounts.runDetails++;
    }, []);
    return (
      <div>
        <output>{JSON.stringify({ params, search: location.search, hash: location.hash })}</output>
        <button onClick={() => setSelection('selected')}>{selection}</button>
      </div>
    );
  };
  return { default: RunDetails };
});

vi.mock('src/pages/NativeUpload', () => ({ default: () => <div>Upload pipeline</div> }));

vi.mock('src/lib/Argo', async (original) => ({
  ...(await original<typeof import('src/lib/Argo')>()),
  setArgoToken: vi.fn(),
}));

/** Points the hash router at a path; the router reads window.location.hash. */
function setHash(path: string) {
  window.history.replaceState(null, '', `/#${path}`);
}

async function navigate(path: string) {
  await act(async () => {
    window.location.hash = `#${path}`;
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

function hashPath(): string {
  return window.location.hash.replace(/^#/, '');
}

describe('Router', () => {
  const originalUrl = window.location.href;

  beforeEach(() => {
    mounts.runDetails = 0;
    setHash('/pipelines');
  });

  afterEach(() => {
    vi.clearAllMocks();
    window.history.replaceState(null, '', originalUrl);
  });

  it('exports the stock route constants the navigation depends on', () => {
    expect(RoutePage.PIPELINES).toBe('/pipelines');
    expect(RoutePage.RECURRING_RUNS).toBe('/recurringruns');
    expect(RoutePrefix.RECURRING_RUN).toBe('/recurringrun');
    expect(RoutePrefix.ARTIFACT).toBe('/artifact');
    expect(ExternalLinks.GITHUB).toMatch(/^https:\/\/github\.com\//);
  });

  it('initial render', () => {
    render(<Router namespace='team' authMode='single-user' />);
    expect(screen.getByText('list:pipelines')).toBeVisible();
    expect(screen.getByTestId('sideNav')).toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('redirects unknown paths to the pipelines list and recovers when navigating to a known route', async () => {
    setHash('/does-not-exist?view=graph');
    render(<Router namespace='team' authMode='single-user' />);
    await waitFor(() => expect(hashPath()).toBe('/pipelines'));
    expect(screen.getByText('list:pipelines')).toBeVisible();

    await navigate('/another-missing-page');
    await waitFor(() => expect(hashPath()).toBe('/pipelines'));

    await navigate('/runs');
    expect(await screen.findByText('list:runs')).toBeVisible();
    expect(screen.queryByText('list:pipelines')).not.toBeInTheDocument();
  });

  it.each([
    ['/pipelines', 'list:pipelines'],
    ['/shared/pipelines', 'list:pipelines:shared'],
    ['/pipeline_versions/new', 'Upload pipeline'],
    ['/experiments', 'list:experiments'],
    ['/archive/experiments', 'list:experiments:archived'],
    ['/experiments/new', 'New experiment'],
    ['/runs', 'list:runs'],
    ['/archive/runs', 'list:runs:archived'],
    ['/compare', 'Compare'],
    ['/recurringruns', 'list:schedules'],
    ['/artifacts', 'list:artifacts'],
  ])('routes %s to its native page', async (path, text) => {
    setHash(path);
    render(<Router namespace='team' authMode='single-user' />);
    expect(await screen.findByText(text)).toBeVisible();
    expect(hashPath()).toBe(path);
  });

  it.each([
    ['/experiments/details/exp%20one', { experimentId: 'exp one' }],
    ['/recurringrun/details/sched-1', { scheduleId: 'sched-1' }],
    ['/artifacts/run-1/node%2F1/output', { runId: 'run-1', nodeId: 'node/1', port: 'output' }],
  ])('decodes the detail parameters in %s', async (path, params) => {
    setHash(path);
    render(<Router namespace='team' authMode='single-user' />);
    expect(await screen.findByRole('status')).toHaveTextContent(JSON.stringify(params));
  });

  // Pages are not keyed by route, so React reuses the NativeListPage instance when
  // /runs changes to /pipelines and its component state (selection, expansion)
  // survives the navigation. Stock keyed each page by location to prevent this.
  it('does not share state between pages', async () => {
    setHash('/runs');
    render(<Router namespace='team' authMode='single-user' />);
    fireEvent.click(screen.getByRole('button', { name: 'list:runs:initial' }));
    expect(screen.getByRole('button', { name: 'list:runs:selected' })).toBeVisible();

    await navigate('/pipelines');
    await waitFor(() => expect(screen.getByText('list:pipelines')).toBeVisible());
    expect(screen.getByRole('button', { name: 'list:pipelines:initial' })).toBeVisible();
  });

  it('preserves Run Details state when only the query changes', async () => {
    setHash('/runs/details/run-1?task=task-1');
    render(<Router namespace='team' authMode='single-user' />);
    expect(screen.getByRole('status')).toHaveTextContent(
      JSON.stringify({ params: { runId: 'run-1' }, search: '?task=task-1', hash: '' }),
    );

    fireEvent.click(screen.getByRole('button', { name: 'initial' }));
    const mountCountBeforeReplace = mounts.runDetails;
    await navigate('/runs/details/run-1');
    await waitFor(() =>
      expect(screen.getByRole('status')).toHaveTextContent(
        JSON.stringify({ params: { runId: 'run-1' }, search: '', hash: '' }),
      ),
    );
    expect(screen.getByRole('button', { name: 'selected' })).toBeVisible();
    expect(mounts.runDetails).toBe(mountCountBeforeReplace);

    await navigate('/runs/details/run-1?task=task-2');
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('task-2'));
    expect(screen.getByRole('button', { name: 'selected' })).toBeVisible();
    expect(mounts.runDetails).toBe(mountCountBeforeReplace);

    await navigate('/runs/details/run-2');
    await waitFor(() =>
      expect(screen.getByRole('status')).toHaveTextContent(
        JSON.stringify({ params: { runId: 'run-2' }, search: '', hash: '' }),
      ),
    );
  });

  it.each([
    ['/pipelines/details/pipeline%20one', { pipelineId: 'pipeline one' }],
    ['/pipelines/details/pipeline%2520one', { pipelineId: 'pipeline%20one' }],
    ['/pipelines/details/pipeline%2Fone/version', { pipelineId: 'pipeline/one' }],
    [
      '/pipelines/details/pipeline-1/version/version%20one',
      { pipelineId: 'pipeline-1', versionId: 'version one' },
    ],
  ])('matches optional and encoded pipeline parameters in %s', async (path, params) => {
    setHash(path);
    render(<Router namespace='team' authMode='single-user' />);
    expect(await screen.findByRole('status')).toHaveTextContent(JSON.stringify(params));
  });

  it('redirects a pipeline details path without an ID to the pipelines list', async () => {
    setHash('/pipelines/details');
    render(<Router namespace='team' authMode='single-user' />);
    await waitFor(() => expect(hashPath()).toBe('/pipelines'));
    expect(screen.getByText('list:pipelines')).toBeVisible();
  });

  it('preserves encoded hash URLs and task query links', () => {
    setHash('/runs/details/run%20one?task=task%2Fiteration+1#node');
    render(<Router namespace='team' authMode='single-user' />);
    expect(screen.getByRole('status')).toHaveTextContent(
      JSON.stringify({
        params: { runId: 'run one' },
        search: '?task=task%2Fiteration+1',
        hash: '#node',
      }),
    );
  });

  // Same cause as the shared-state case above: NativeNewRun seeds its state from
  // the query once, and a navigation to /runs/new with a different query reuses
  // the mounted instance, so the form keeps the previous query's values.
  it('reinitializes query-derived forms on navigation', async () => {
    setHash('/runs/new?name=first');
    render(<Router namespace='team' authMode='single-user' />);
    expect(screen.getByRole('textbox', { name: 'Name' })).toHaveValue('first');
    await navigate('/runs/new?name=second');
    await waitFor(() =>
      expect(screen.getByRole('textbox', { name: 'Name' })).toHaveValue('second'),
    );
  });

  it('highlights the current section in the side navigation', async () => {
    setHash('/runs/details/run-1');
    render(<Router namespace='team' authMode='single-user' />);
    const runs = screen.getByRole('link', { name: 'Runs List' });
    expect(runs.querySelector('button')?.className).toMatch(/active/);
    expect(
      screen.getByRole('link', { name: 'Pipeline List' }).querySelector('button')?.className,
    ).not.toMatch(/active/);
    fireEvent.click(screen.getByRole('link', { name: 'Pipeline List' }));
    expect(await screen.findByText('list:pipelines')).toBeVisible();
    expect(hashPath()).toBe('/pipelines');
  });

  describe('connection', () => {
    it('requires a bearer token before rendering pages in token mode', async () => {
      render(<Router namespace='team' />);
      expect(screen.queryByText('list:pipelines')).not.toBeInTheDocument();
      expect(screen.getByRole('dialog')).toHaveTextContent('Connect to Kubeflow Pipelines');
      expect(screen.getByRole('dialog')).toHaveTextContent('Namespace: team.');
      const connect = screen.getByRole('button', { name: 'Connect' });
      expect(connect).toBeDisabled();

      const token = screen.getByLabelText('Kubernetes bearer token');
      fireEvent.change(token, { target: { value: '   ' } });
      expect(connect).toBeDisabled();
      fireEvent.change(token, { target: { value: 'secret-token' } });
      expect(connect).toBeEnabled();
      fireEvent.click(connect);

      expect(setArgoToken).toHaveBeenCalledWith('secret-token');
      expect(screen.getByText('list:pipelines')).toBeVisible();
      await waitFor(() =>
        expect(screen.queryByText('Connect to Kubeflow Pipelines')).not.toBeInTheDocument(),
      );
    });

    it('prompts for a valid namespace label in multi-user mode without one', () => {
      const onNamespace = vi.fn();
      render(<Router namespace='' authMode='multi-user' onNamespace={onNamespace} />);
      expect(screen.queryByText('list:pipelines')).not.toBeInTheDocument();
      expect(screen.getByRole('dialog')).toHaveTextContent(
        'Enter the namespace whose pipelines you want to work with.',
      );
      const connect = screen.getByRole('button', { name: 'Connect' });
      const namespace = screen.getByLabelText('Namespace');

      fireEvent.change(namespace, { target: { value: 'Not A Label' } });
      expect(connect).toBeDisabled();
      fireEvent.change(namespace, { target: { value: '-leading-dash' } });
      expect(connect).toBeDisabled();
      fireEvent.change(namespace, { target: { value: ' team-a ' } });
      expect(connect).toBeEnabled();
      fireEvent.click(connect);
      expect(onNamespace).toHaveBeenCalledWith('team-a');
      expect(setArgoToken).not.toHaveBeenCalled();
    });

    it('renders pages directly once multi-user mode has a namespace', () => {
      render(<Router namespace='team' authMode='multi-user' />);
      expect(screen.getByText('list:pipelines')).toBeVisible();
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
  });

  describe('page feedback', () => {
    it('shows page errors in a dialog without changing the location', async () => {
      setHash('/compare?runs=a,b');
      render(<Router namespace='team' authMode='single-user' />);
      fireEvent.click(screen.getByRole('button', { name: 'Fail loading' }));
      const dialog = await screen.findByRole('dialog');
      expect(dialog).toHaveTextContent('Error');
      expect(dialog).toHaveTextContent('Current load error');
      expect(hashPath()).toBe('/compare?runs=a,b');
      fireEvent.click(screen.getByRole('button', { name: 'OK' }));
      await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
      expect(screen.getByText('Compare')).toBeVisible();
      expect(hashPath()).toBe('/compare?runs=a,b');
    });

    it('asks for confirmation and reports a failed action in the error dialog', async () => {
      setHash('/compare');
      render(<Router namespace='team' authMode='single-user' />);

      fireEvent.click(screen.getByRole('button', { name: 'Delete' }));
      const confirmation = await screen.findByRole('dialog');
      expect(confirmation).toHaveTextContent('Delete run?');
      expect(confirmation).toHaveTextContent('This cannot be undone.');
      fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
      await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());

      fireEvent.click(screen.getByRole('button', { name: 'Delete' }));
      fireEvent.click(await screen.findByRole('button', { name: 'Confirm' }));
      await waitFor(() => expect(screen.getByRole('dialog')).toHaveTextContent('denied'));
      expect(screen.getByRole('dialog')).not.toHaveTextContent('Delete run?');
    });
  });
});
