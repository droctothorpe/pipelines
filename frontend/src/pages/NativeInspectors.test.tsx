// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import { afterEach, expect, it, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { NativeArtifactContent } from './NativeInspectors';

vi.mock('src/lib/NativeUiContext', () => ({ useNativeUi: () => ({ fail: vi.fn() }) }));
afterEach(() => vi.unstubAllGlobals());

it('renders Markdown structure without raw HTML execution or automatic external images', async () => {
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
  expect(view.container.querySelector('img[src^="http"]')).toBeNull();
  expect(view.container.querySelector('a[href^="javascript:"]')).toBeNull();
  expect(vi.mocked(fetch).mock.calls).toHaveLength(1);
});
