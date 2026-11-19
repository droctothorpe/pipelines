// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect } from 'vitest';
import NativeTable, { tablePage } from './NativeTable';

describe('native inventory in the stock table', () => {
  it('sorts the stock artifact columns by their actual values', () => {
    const rows = [
      { id: 'one', name: 'first', otherFields: [], sortValues: { type: 'system.Model' } },
      { id: 'two', name: 'second', otherFields: [], sortValues: { type: 'system.Dataset' } },
    ];
    expect(
      tablePage(rows, { sortBy: 'type', orderAscending: true }).rows.map((row) => row.id),
    ).toEqual(['two', 'one']);
  });
  it('updates pagination when a refreshed inventory grows, without clearing selection', async () => {
    const user = userEvent.setup();
    const columns = [{ label: 'Run name', sortKey: 'name' }];
    const props = { columns, filterLabel: 'Filter runs', selected: ['run-00'], select: () => {} };
    const view = render(<NativeTable {...props} rows={[]} />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Next page' })).toBeDisabled());
    const rows = Array.from({ length: 12 }, (_, i) => ({
      id: `run-${String(i).padStart(2, '0')}`,
      name: `run-${String(i).padStart(2, '0')}`,
      otherFields: [`run-${String(i).padStart(2, '0')}`],
    }));
    view.rerender(<NativeTable {...props} rows={rows} />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Next page' })).toBeEnabled());
    await user.click(screen.getByRole('button', { name: 'Next page' }));
    expect(await screen.findByText('run-00')).toBeInTheDocument();
    expect(
      screen.getAllByRole('checkbox').filter((input) => (input as HTMLInputElement).checked),
    ).toHaveLength(1);
  });
});
