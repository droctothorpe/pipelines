// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import { act, cleanup, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  config: undefined as undefined | ((value: unknown) => void),
  dashboard: '' as string,
}));
vi.mock('src/build/tailwind.output.css', () => ({}));
vi.mock('@xyflow/react/dist/style.css', () => ({}));
vi.mock('src/lib/Argo', () => ({
  getUiConfig: () => new Promise((resolve) => (mocks.config = resolve)),
}));
vi.mock('src/lib/Dashboard', () => ({ useDashboardNamespace: () => mocks.dashboard || undefined }));
vi.mock('src/components/Router', () => ({
  default: ({ namespace }: { namespace: string }) => <div>router:{namespace}</div>,
}));

import { App } from './argo';

afterEach(cleanup);
beforeEach(() => {
  mocks.config = undefined;
  mocks.dashboard = '';
});

function mount() {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <App />
    </QueryClientProvider>,
  );
}

it('keeps a deep link while the proxy config loads (C56)', async () => {
  window.location.hash = '#/runs/details/run-1';
  mount();
  expect(mocks.config).toBeDefined();
  await act(async () => {
    mocks.config!({ authMode: 'single-user', namespace: 'kfp-argo' });
  });
  expect(await screen.findByText('router:kfp-argo')).toBeTruthy();
  expect(window.location.hash).toBe('#/runs/details/run-1');
});

it('falls back to the list when the dashboard switches namespace after load', async () => {
  window.location.hash = '#/runs/details/run-1';
  const view = mount();
  await act(async () => {
    mocks.config!({ authMode: 'multi-user', namespace: '' });
  });
  mocks.dashboard = 'team-a';
  view.rerender(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <App />
    </QueryClientProvider>,
  );
  await screen.findByText('router:team-a');
  mocks.dashboard = 'team-b';
  await act(async () => {
    view.rerender(
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <App />
      </QueryClientProvider>,
    );
  });
  expect(window.location.hash).toBe('#/runs');
});
