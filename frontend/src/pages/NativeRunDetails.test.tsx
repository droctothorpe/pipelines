// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Routes, Route, Link } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
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
  default: ({ value }: { value: string }) => <pre>{value}</pre>,
}));
const run = {
  metadata: {
    name: 'run-one',
    namespace: 'argo',
    uid: 'uid-one',
    labels: { 'pipelines.kubeflow.org/experiment': 'training' },
  },
  spec: {},
  status: {
    phase: 'Succeeded',
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
        memoizationStatus: { hit: true },
        outputs: {
          artifacts: [{ name: 'kfp-metadata' }, { name: 'dataset' }],
          parameters: [{ name: 'kfp-meta-dataset', value: '{"internal":true}' }],
        },
      },
    },
  },
};
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
const clients: QueryClient[] = [];
function setup(path = '/runs/details/uid-one', otherRuns: unknown[] = []) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url.includes('/artifacts/')) return new Response(JSON.stringify(metadata));
      if (url.includes('/api/v1/workflows/argo/run-one')) return new Response(JSON.stringify(run));
      if (url.includes('/archived-workflows')) return new Response(JSON.stringify({ items: [] }));
      if (url.includes('/configmaps'))
        return new Response(
          JSON.stringify({
            items: [
              {
                apiVersion: 'v1',
                kind: 'ConfigMap',
                metadata: { name: 'training' },
                data: { displayName: 'Human training', description: 'Training group' },
              },
            ],
          }),
        );
      if (url.includes('/workflow-templates') || url.includes('/cron-workflows'))
        return new Response(JSON.stringify({ items: [] }));
      if (url.startsWith('/kubernetes/apis/argoproj.io/'))
        return new Response(JSON.stringify({ items: [run, ...otherRuns] }));
      throw new Error(`Unexpected request: ${url}`);
    }),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  clients.push(client);
  const view = render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path='/runs/details/:runId' element={<NativeRunDetails />} />
          <Route path='/experiments/details/:experimentId' element={<NativeExperimentDetails />} />
          <Route
            path='/compare'
            element={
              <>
                <Link to='/compare?runlist=uid-one'>Compare selected</Link>
                <NativeCompare />
              </>
            }
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { client, ...view };
}
afterEach(() => {
  cleanup();
  clients.splice(0).forEach((client) => client.clear());
  vi.unstubAllGlobals();
});

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
  it('retains the selected task across refresh and exposes cached artifact provenance', async () => {
    const { client } = setup();
    fireEvent.click(await screen.findByRole('button', { name: 'prepare', exact: true }));
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
    await screen.findByRole('button', { name: 'prepare', exact: true });
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
