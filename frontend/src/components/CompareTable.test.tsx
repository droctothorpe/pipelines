// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import { render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import CompareTable from './CompareTable';
import { logger } from 'src/lib/UiUtils';

let loggerSpy: ReturnType<typeof vi.spyOn>;

const rows = [
  ['1', '2', '3'],
  ['4', '5', '6'],
  ['cell7', 'cell8', 'cell9'],
];
const xLabels = ['col1', 'col2', 'col3'];
const yLabels = ['row1', 'row2', 'row3'];

describe('CompareTable', () => {
  beforeEach(() => {
    loggerSpy = vi.spyOn(logger, 'error').mockImplementation(() => undefined);
  });

  afterEach(() => {
    loggerSpy.mockRestore();
  });

  it('renders no data', () => {
    const { container } = render(<CompareTable rows={[]} xLabels={[]} yLabels={[]} />);
    expect(container.firstChild).toBeNull();
    expect(loggerSpy).not.toHaveBeenCalled();
  });

  it('logs error if ylabels and rows have different lengths', () => {
    render(<CompareTable rows={[rows[0], rows[1]]} xLabels={xLabels} yLabels={yLabels} />);
    expect(loggerSpy).toHaveBeenCalledWith(
      'Number of rows (2) should match the number of Y labels (3).',
    );
  });

  it('renders one row with three columns', () => {
    const { container } = render(<CompareTable rows={rows} xLabels={xLabels} yLabels={yLabels} />);
    const tableRows = Array.from(container.querySelectorAll('tr'));
    expect(tableRows).toHaveLength(4);
    const cellText = (row: Element) =>
      Array.from(row.querySelectorAll('td')).map((cell) => cell.textContent);
    expect(cellText(tableRows[0])).toEqual(['', ...xLabels]);
    expect(cellText(tableRows[1])).toEqual(['row1', '1', '2', '3']);
    expect(cellText(tableRows[2])).toEqual(['row2', '4', '5', '6']);
    expect(cellText(tableRows[3])).toEqual(['row3', 'cell7', 'cell8', 'cell9']);
    // Every cell exposes its full text as a title for truncated labels.
    expect(screen.getByText('cell9')).toHaveAttribute('title', 'cell9');
    expect(screen.getByText('col1')).toHaveAttribute('title', 'col1');
    expect(loggerSpy).not.toHaveBeenCalled();
  });
});

describe('CompareTable xParentLabels', () => {
  beforeEach(() => {
    loggerSpy = vi.spyOn(logger, 'error').mockImplementation(() => undefined);
  });

  afterEach(() => {
    loggerSpy.mockRestore();
  });
  const xParentLabels = [
    { colSpan: 2, label: 'parent1' },
    { colSpan: 1, label: 'parent2' },
  ];

  it('Hide x-axis parent labels if xlabels and xparentlabels have different lengths', () => {
    render(
      <CompareTable
        rows={rows}
        xLabels={xLabels}
        yLabels={yLabels}
        xParentLabels={[xParentLabels[0]]}
      />,
    );

    expect(loggerSpy).toHaveBeenCalledWith(
      'Number of columns with data (3) should match the aggregated length of parent columns (2).',
    );
    expect(screen.queryByText(xParentLabels[0].label)).toBeNull();
  });

  it('X-axis parent labels present if xlabels and xparentlabels have appropriate lengths', () => {
    render(
      <CompareTable
        rows={rows}
        xLabels={xLabels}
        yLabels={yLabels}
        xParentLabels={xParentLabels}
      />,
    );

    expect(screen.getByText(xParentLabels[0].label)).toHaveAttribute('colspan', '2');
    expect(screen.getByText(xParentLabels[1].label)).toHaveAttribute('colspan', '1');
  });
});
