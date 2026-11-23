// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import { afterEach, expect, it, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { NativeArtifactContent } from './NativeInspectors';

vi.mock('src/lib/NativeUiContext', () => ({ useNativeUi: () => ({ fail: vi.fn() }) }));
afterEach(() => vi.unstubAllGlobals());

it('renders Markdown as stock does: no raw HTML, sanitized links, images as written', async () => {
  const producer = { run: 'run-id', task: 'pod', namespace: 'team' };
  const metadata = {
    schema: 'kfp-argo/v1',
    producer,
    inputs: [],
    metrics: {},
    artifacts: [
      {
        port: 'report',
        type: 'system.Markdown@0.0.1',
        uri: 's3://bucket/report',
        metadata: {},
        producer,
      },
    ],
  };
  vi.stubGlobal(
    'fetch',
    vi.fn(
      async () =>
        new Response(
          '## Evaluation\n\n**passed**\n\n![tracking](https://tracker.example/pixel)\n\n<script>alert(1)</script>\n\n[bad](javascript:alert(1))',
        ),
    ),
  );
  const view = render(
    <MemoryRouter>
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <NativeArtifactContent
          run={{ metadata: { name: 'wf', uid: 'run-id', namespace: 'team' }, spec: {} }}
          node={{
            id: 'node',
            displayName: 'produce',
            type: 'Pod',
            outputs: { parameters: [{ name: 'kfp-metadata', value: JSON.stringify(metadata) }] },
          }}
          port='report'
        />
      </QueryClientProvider>
    </MemoryRouter>,
  );
  await screen.findByText('system.Markdown@0.0.1');
  fireEvent.click(screen.getByRole('button', { name: 'Visualization', exact: true }));
  expect(await screen.findByRole('heading', { name: 'Evaluation' })).toBeTruthy();
  expect(view.container.querySelector('strong')?.textContent).toBe('passed');
  expect(view.container.querySelector('script')).toBeNull();
  // Stock parity (C24): the parser's sanitizer drops javascript: links and
  // remote images render as written, nothing beyond the stock viewer.
  expect(view.container.querySelector('a[href^="javascript:"]')).toBeNull();
  expect(view.container.querySelector('img')?.getAttribute('src')).toBe(
    'https://tracker.example/pixel',
  );
  expect(vi.mocked(fetch).mock.calls).toHaveLength(1);
});

it('routes a legacy mlpipeline-ui-metadata artifact to the kept viewers', async () => {
  const producer = { run: 'run-id', task: 'pod', namespace: 'team' };
  const metadata = {
    schema: 'kfp-argo/v1',
    producer,
    inputs: [],
    metrics: {},
    artifacts: [
      {
        port: 'mlpipeline_ui_metadata',
        type: 'system.Artifact@0.0.1',
        uri: 's3://bucket/run/pod/mlpipeline_ui_metadata',
        metadata: {},
        producer,
      },
      {
        port: 'table',
        type: 'system.Artifact@0.0.1',
        uri: 's3://bucket/run/pod/table',
        metadata: {},
        producer,
      },
    ],
  };
  const uiMetadata = {
    outputs: [
      {
        type: 'table',
        format: 'csv',
        header: ['model', 'accuracy'],
        source: 's3://bucket/run/pod/table',
      },
      {
        type: 'confusion_matrix',
        format: 'csv',
        schema: [{ name: 'target' }, { name: 'predicted' }, { name: 'count' }],
        labels: ['neg', 'pos'],
        storage: 'inline',
        source: 'neg,neg,3\nneg,pos,1\npos,neg,1\npos,pos,5\n',
      },
      { type: 'markdown', storage: 'inline', source: '## Legacy summary' },
      {
        type: 'web-app',
        storage: 'inline',
        source: '<h1>Legacy web app</h1><script>document.title = "x"</script>',
      },
      { type: 'tensorboard', source: 's3://bucket/run/pod/logs' },
      { type: 'table', format: 'csv', header: ['x'], source: 's3://elsewhere/data.csv' },
    ],
  };
  vi.stubGlobal(
    'fetch',
    vi.fn(
      async (url: string) =>
        new Response(
          url.endsWith('/table') ? 'baseline,0.81\ntuned,0.94\n' : JSON.stringify(uiMetadata),
        ),
    ),
  );
  render(
    <MemoryRouter>
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <NativeArtifactContent
          run={{ metadata: { name: 'wf', uid: 'run-id', namespace: 'team' }, spec: {} }}
          node={{
            id: 'node',
            displayName: 'summarize',
            type: 'Pod',
            outputs: { parameters: [{ name: 'kfp-metadata', value: JSON.stringify(metadata) }] },
          }}
          port='mlpipeline_ui_metadata'
        />
      </QueryClientProvider>
    </MemoryRouter>,
  );
  await screen.findByText('system.Artifact@0.0.1');
  fireEvent.click(screen.getByRole('button', { name: 'Visualization', exact: true }));
  const table = await screen.findByRole('table', { name: 'Legacy table' });
  expect(table.textContent).toContain('tuned');
  expect(await screen.findByRole('heading', { name: 'Legacy summary' })).toBeTruthy();
  expect(screen.getByRole('region', { name: 'confusion_matrix visualization' })).toBeTruthy();
  // Stock's HTML viewer sandbox: scripts allowed, same-origin not, content verbatim.
  const frame = screen.getByTitle('Legacy web app 4');
  expect(frame.getAttribute('sandbox')).toBe('allow-scripts');
  expect(frame.getAttribute('srcdoc')).toBe(
    '<h1>Legacy web app</h1><script>document.title = "x"</script>',
  );
  expect(screen.getByText(/TensorBoard viewers are not launched/).textContent).toContain(
    's3://bucket/run/pod/logs',
  );
  expect(screen.getByText(/not an output artifact of this task/).textContent).toContain(
    's3://elsewhere/data.csv',
  );
  const urls = vi.mocked(fetch).mock.calls.map(([url]) => String(url));
  expect(urls).toEqual([
    '/argo/artifacts/team/wf/node/mlpipeline_ui_metadata',
    '/argo/artifacts/team/wf/node/table',
  ]);
});
