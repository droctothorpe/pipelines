// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { NativeUiContext, type Confirmation } from 'src/lib/NativeUiContext';
import { setExperimentStorage } from 'src/lib/NativeUi';
import { setScheduleSuspended } from 'src/lib/ArgoResources';
import NativeExperimentDetails from './NativeExperimentDetails';

const mocks = vi.hoisted(() => ({ inventory: undefined as any }));
vi.mock('src/lib/NativeQueries', () => ({ useInventory: () => mocks.inventory }));
vi.mock('src/atoms/MD2Tabs', () => ({
  default: ({ tabs, selectedTab, onSwitch }: any) => (
    <div>
      {tabs.map((tab: string, index: number) => (
        <button
          key={tab}
          role='tab'
          aria-selected={selectedTab === index}
          onClick={() => onSwitch(index)}
        >
          {tab}
        </button>
      ))}
    </div>
  ),
}));
vi.mock('src/lib/NativeUi', async (original) => ({
  ...(await original<typeof import('src/lib/NativeUi')>()),
  setExperimentStorage: vi.fn(),
}));
vi.mock('src/lib/ArgoResources', async (original) => ({
  ...(await original<typeof import('src/lib/ArgoResources')>()),
  setScheduleSuspended: vi.fn(async () => undefined),
}));
afterEach(cleanup);
beforeEach(() => vi.clearAllMocks());

function setup(storageState = 'AVAILABLE') {
  const query = (data: unknown[]) => ({ data, refetch: vi.fn(async () => ({})) });
  mocks.inventory = {
    experiments: query([
      {
        apiVersion: 'v1',
        kind: 'ConfigMap',
        metadata: { name: 'experiment', uid: 'exp-id', namespace: 'team', resourceVersion: '1' },
        data: { displayName: 'Training', storageState },
      },
    ]),
    runs: query([]),
    schedules: query([]),
    versions: query([]),
    pipelines: query([]),
  };
  const confirm = vi.fn<(value: Confirmation) => void>();
  const ui = () => (
    <NativeUiContext.Provider value={{ namespace: 'team', fail: vi.fn(), confirm }}>
      <MemoryRouter initialEntries={['/experiments/details/exp-id']}>
        <Routes>
          <Route path='/experiments/details/:experimentId' element={<NativeExperimentDetails />} />
        </Routes>
      </MemoryRouter>
    </NativeUiContext.Provider>
  );
  const view = render(ui());
  return { confirm, rerender: () => view.rerender(ui()) };
}

it('opens an archived experiment on Archived without overriding a later tab selection', () => {
  const page = setup('ARCHIVED');
  expect(screen.getByRole('tab', { name: 'Archived' })).toHaveAttribute('aria-selected', 'true');
  fireEvent.click(screen.getByRole('tab', { name: 'Active' }));
  page.rerender();
  expect(screen.getByRole('tab', { name: 'Active' })).toHaveAttribute('aria-selected', 'true');
});

it.each([false, true])(
  'refreshes child inventories after archive, including partial failure=%s',
  async (failure) => {
    const page = setup();
    if (failure) vi.mocked(setExperimentStorage).mockRejectedValueOnce(new Error('denied'));
    else vi.mocked(setExperimentStorage).mockResolvedValueOnce(undefined);
    fireEvent.click(screen.getByRole('button', { name: 'Archive' }));
    const confirmation = page.confirm.mock.calls[0][0];
    expect(confirmation.content).toContain('recurring runs');
    await act(async () => {
      if (failure) await expect(confirmation.action()).rejects.toThrow('denied');
      else await confirmation.action();
    });
    for (const name of ['experiments', 'runs', 'schedules'])
      expect(mocks.inventory[name].refetch).toHaveBeenCalledTimes(1);
    if (!failure)
      expect(screen.getByRole('tab', { name: 'Archived' })).toHaveAttribute(
        'aria-selected',
        'true',
      );
  },
);

it('toggles a recurring run from the manage dialog, as stock does (C36)', async () => {
  setup();
  const schedule = {
    apiVersion: 'argoproj.io/v1alpha1',
    kind: 'CronWorkflow',
    metadata: { name: 'nightly', uid: 'cron-1', namespace: 'team' },
    spec: {
      schedules: ['0 2 * * *'],
      suspend: false,
      workflowMetadata: { labels: { 'pipelines.kubeflow.org/experiment': 'exp-id' } },
    },
  };
  mocks.inventory.schedules = { data: [schedule], refetch: vi.fn(async () => ({})) };
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: 'Manage' }));
  });
  const toggle = screen.getByLabelText('Enable nightly') as HTMLInputElement;
  expect(toggle.checked).toBe(true);
  await act(async () => {
    fireEvent.click(toggle);
  });
  expect(vi.mocked(setScheduleSuspended)).toHaveBeenCalledWith('team', schedule, true);
  expect(mocks.inventory.schedules.refetch).toHaveBeenCalled();
});
