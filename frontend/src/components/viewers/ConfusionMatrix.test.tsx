// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import { fireEvent, render, waitFor } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import ConfusionMatrix, { ConfusionMatrixConfig } from './ConfusionMatrix';
import { PlotType } from './Viewer';

describe('ConfusionMatrix', () => {
  const data = [
    [0, 1, 2],
    [3, 4, 5],
    [6, 7, 8],
  ];
  const config: ConfusionMatrixConfig = {
    axes: ['test x axis', 'test y axis'],
    data,
    labels: ['label1', 'label2'],
    type: PlotType.CONFUSION_MATRIX,
  };

  // Numeric data cells in document order (the displayed, y-reversed orientation).
  const displayedValues = (container: HTMLElement) =>
    Array.from(container.querySelectorAll('td'))
      .map((cell) => cell.textContent?.trim())
      .filter((text) => text && /^\d+$/.test(text))
      .map(Number);

  it('does not break on empty data', () => {
    const { container } = render(<ConfusionMatrix configs={[]} />);
    expect(container.firstChild).toBeNull();
  });

  it('renders a basic confusion matrix', () => {
    const { container, getByText, getAllByRole } = render(<ConfusionMatrix configs={[config]} />);
    expect(container.querySelectorAll('table')).toHaveLength(1);
    // Only the labeled classes are plotted; the last row is shown first.
    expect(displayedValues(container)).toEqual([1, 4, 0, 3]);
    const rowLabels = Array.from(container.querySelectorAll('tr > td:first-child > div')).map(
      (label) => label.textContent,
    );
    expect(rowLabels).toEqual(['label2', 'label1']);
    expect(
      getAllByRole('columnheader')
        .filter((header) => header.getAttribute('scope') === 'col')
        .map((header) => header.textContent),
    ).toEqual(['label1', 'label2']);
    expect(getByText('test x axis')).toBeInTheDocument();
    expect(getByText('test y axis')).toBeInTheDocument();
    // The legend runs from zero to the largest value in the data.
    const legendLabels = Array.from(container.querySelectorAll('div > span')).map(
      (label) => label.textContent,
    );
    expect(legendLabels).toEqual(['8', '0', '1', '3', '4', '6']);
  });

  it('does not break on asymetric data', () => {
    const testConfig = { ...config, data: data.slice(1) };
    const { container } = render(<ConfusionMatrix configs={[testConfig]} />);
    expect(displayedValues(container)).toEqual([4, 7, 3, 6]);
    expect(container.querySelectorAll('tbody tr')).toHaveLength(5);
  });

  it('renders only one of the given list of configs', () => {
    const { container } = render(<ConfusionMatrix configs={[config, config, config]} />);
    expect(container.querySelectorAll('table')).toHaveLength(1);
    expect(displayedValues(container)).toEqual([1, 4, 0, 3]);
  });

  it('renders a small confusion matrix snapshot, with no labels or footer', () => {
    const { container, queryByText } = render(
      <ConfusionMatrix configs={[config]} maxDimension={100} />,
    );
    expect(displayedValues(container)).toEqual([1, 4, 0, 3]);
    expect(queryByText('test x axis')).toBeNull();
    expect(queryByText('test y axis')).toBeNull();
    expect(queryByText('label1')).toBeNull();
    expect(queryByText('label2')).toBeNull();
    expect(container.querySelectorAll('th')).toHaveLength(0);
    expect(container.querySelectorAll('tbody tr')).toHaveLength(2);
    // No legend is rendered beside the table.
    expect(container.querySelectorAll('div > span')).toHaveLength(0);
  });

  it('keeps long column labels and the axis caption in the table flow', () => {
    const labels = ['negative-class-with-a-long-name', 'positive class with a long name'];
    const { container, getAllByRole, getByText } = render(
      <ConfusionMatrix configs={[{ ...config, labels }]} />,
    );
    const columnLabels = getAllByRole('columnheader').filter(
      (header) => header.getAttribute('scope') === 'col',
    );

    expect(columnLabels).toHaveLength(2);
    columnLabels.forEach((header, index) => {
      expect(header).toHaveTextContent(labels[index]);
      expect(header).not.toHaveStyle('position: absolute');
      expect(header.firstElementChild).toHaveStyle('overflow-wrap: anywhere; width: 79px');
    });
    const axisCaption = getByText(config.axes[0]);
    expect(axisCaption).toHaveAttribute('colspan', '2');
    expect(axisCaption.parentElement).toBe(container.querySelector('tbody')?.lastElementChild);
    expect(axisCaption).not.toHaveStyle('position: absolute');
  });

  it('keeps distinct comparison values in the displayed matrix orientation', () => {
    const { container, rerender } = render(
      <ConfusionMatrix
        configs={[
          {
            ...config,
            data: [
              [42, 8],
              [3, 47],
            ],
          },
        ]}
      />,
    );

    expect(displayedValues(container)).toEqual([8, 47, 42, 3]);
    rerender(
      <ConfusionMatrix
        configs={[
          {
            ...config,
            data: [
              [38, 12],
              [7, 43],
            ],
          },
        ]}
      />,
    );
    expect(displayedValues(container)).toEqual([12, 43, 38, 7]);
  });

  it('activates row/column on cell hover', () => {
    const { container } = render(<ConfusionMatrix configs={[config]} />);
    const cells = container.querySelectorAll('td');
    expect(cells.length).toBeGreaterThan(2);
    const targetCell = cells[2];
    fireEvent.mouseOver(targetCell);
    const overlay = targetCell.querySelector('div');
    expect(overlay).not.toBeNull();
    expect(overlay).toHaveStyle('opacity: 0.05');
  });

  it('applies refreshed data without resetting the active cell', async () => {
    const { container, rerender } = render(<ConfusionMatrix configs={[config]} />);
    const targetCell = container.querySelectorAll('td')[2];
    fireEvent.mouseOver(targetCell);

    rerender(
      <ConfusionMatrix
        configs={[{ ...config, data: config.data.map((row) => row.map((value) => value + 10)) }]}
      />,
    );

    await waitFor(() => expect(container.querySelectorAll('td')[2]).toHaveTextContent('11'));
    const refreshedTarget = container.querySelectorAll('td')[2];
    expect(refreshedTarget.querySelector('div')).toHaveStyle('opacity: 0.05');
  });

  it('returns a user friendly display name', () => {
    expect(ConfusionMatrix.prototype.getDisplayName()).toBe('Confusion matrix');
  });
});
