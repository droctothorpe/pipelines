// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Column, Row } from './CustomTable';
import { CustomTableRow } from './CustomTableRow';

describe('CustomTableRow', () => {
  const columns: Column[] = [
    {
      customRenderer: undefined,
      label: 'col1',
    },
    {
      customRenderer: undefined,
      label: 'col2',
    },
  ];

  const row: Row = {
    id: 'row',
    otherFields: ['cell1', 'cell2'],
  };

  it('renders some rows using a custom renderer', () => {
    const customColumns: Column[] = [
      { ...columns[0], customRenderer: () => <span>this is custom output</span> },
      columns[1],
    ];
    const { container } = render(<CustomTableRow row={row} columns={customColumns} />);
    const cells = Array.from(container.children) as HTMLElement[];
    expect(cells).toHaveLength(2);
    expect(cells[0]).toHaveStyle({ width: '50%' });
    expect(cells[1]).toHaveStyle({ width: '50%' });
    expect(screen.getByText('this is custom output')).toBeInTheDocument();
    expect(screen.queryByText('cell1')).toBeNull();
    expect(screen.getByText('cell2')).toBeInTheDocument();
  });

  it('displays warning icon with tooltip if row has error', () => {
    const { container } = render(
      <CustomTableRow row={{ ...row, error: 'dummy error' }} columns={columns} />,
    );
    const cells = Array.from(container.children) as HTMLElement[];
    const icon = cells[0].querySelector('svg');
    expect(icon).not.toBeNull();
    expect(icon).toHaveAttribute('aria-label', 'dummy error');
    expect(cells[1].querySelector('svg')).toBeNull();
    expect(screen.getByText('cell1')).toBeInTheDocument();
    expect(screen.getByText('cell2')).toBeInTheDocument();
  });
});
