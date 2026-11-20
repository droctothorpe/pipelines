// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import { afterEach, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { NativeArtifactPreview } from './NativeArtifactPreview';

const run = { metadata: { name: 'run', uid: 'run-uid', namespace: 'team' }, spec: {} };
const node = {
  id: 'node',
  name: 'producer',
  displayName: 'producer',
  type: 'Pod',
  phase: 'Succeeded',
};
const artifact = {
  port: 'dataset',
  type: 'system.Dataset@0.0.1',
  uri: 's3://bucket/data',
  producer: { run: 'run-uid', task: 'producer', namespace: 'team' },
  metadata: { _kfp_preview: { version: 2, storage: 'sibling' } },
};
const preview = {
  version: 1,
  kind: 'dataset',
  format: 'CSV',
  columns: [{ name: 'value', dtype: 'string' }],
  rows: [['hello']],
  total_rows: 1,
  total_columns: 1,
  sample: {
    method: 'head',
    rows_truncated: false,
    columns_truncated: false,
    values_truncated: false,
    redacted: false,
    rows_omitted: false,
  },
};
afterEach(() => vi.unstubAllGlobals());
function show(value = artifact) {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <NativeArtifactPreview run={run} node={node} artifact={value} />
    </QueryClientProvider>,
  );
}
it('uses the bounded sibling preview and stock dataset table, never the dataset payload', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(JSON.stringify(preview))),
  );
  show();
  expect(await screen.findByRole('table', { name: 'Dataset sample' })).toBeTruthy();
  expect(screen.getByText('hello')).toBeTruthy();
  expect(vi.mocked(fetch).mock.calls[0][0]).toBe('/argo/artifacts/team/run/node/dataset-preview');
  expect(
    vi
      .mocked(fetch)
      .mock.calls.every(([url]) => url === '/argo/artifacts/team/run/node/dataset-preview'),
  ).toBe(true);
});
it('does not download model weights when the preview is absent', async () => {
  vi.stubGlobal('fetch', vi.fn());
  show({ ...artifact, type: 'system.Model@0.0.1', metadata: {} as typeof artifact.metadata });
  expect(await screen.findByText(/No preview is available/)).toBeTruthy();
  expect(fetch).not.toHaveBeenCalled();
});
it('rejects oversized previews before parsing them', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response('x'.repeat(65537))),
  );
  show();
  fireEvent.click(await screen.findByRole('button', { name: 'Details' }));
  expect(await screen.findByText(/64 KiB/)).toBeTruthy();
});
