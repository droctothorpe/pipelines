// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { DatasetPreview, ModelPreview } from 'src/lib/v2/ArtifactContentPreview';
import { DatasetPreviewTable, ModelPreviewSummary } from './ArtifactContentPreview';

const dataset: DatasetPreview = {
  version: 1,
  kind: 'dataset',
  format: 'parquet',
  columns: [
    { name: 'feature_a', dtype: 'float64' },
    { name: 'feature_b', dtype: 'int64' },
    { name: 'label', dtype: 'string' },
  ],
  rows: Array.from({ length: 10 }, (_, index) => [
    Number(((index + 1) / 10).toFixed(1)),
    index,
    `class-${index % 2}`,
  ]),
  total_rows: 1000,
  total_columns: 3,
  sample: {
    method: 'head',
    rows_truncated: true,
    columns_truncated: false,
    values_truncated: false,
    redacted: false,
    rows_omitted: false,
  },
};

const model: ModelPreview = {
  version: 1,
  kind: 'model',
  framework: { name: 'xgboost', version: '2.1.0' },
  estimator_class: 'xgboost.XGBClassifier',
  hyperparameters: { n_estimators: 100, max_depth: 6, learning_rate: 0.3, booster: 'gbtree' },
  structure: { tree_count: 100, feature_count: 3 },
  notes: ['Weights are not included in the preview.'],
};

describe('artifact content previews', () => {
  it('preserves sample order and shows dimensions and dtypes', () => {
    render(<DatasetPreviewTable preview={dataset} />);
    const table = screen.getByRole('table', { name: 'Dataset sample' });
    expect(within(table).getAllByRole('row')).toHaveLength(11);
    expect(within(table).getAllByRole('row')[1]).toHaveTextContent('0.1');
    expect(within(table).getAllByRole('row')[2]).toHaveTextContent('0.2');
    expect(within(table).getAllByRole('row')[10]).toHaveTextContent('1');
    expect(screen.getByRole('status')).toHaveTextContent('Showing 10 of 1000 rows; 3 of 3 columns');
    expect(screen.getByRole('heading', { name: 'Dataset preview (parquet)' })).toBeVisible();
    expect(screen.getByText('float64')).toBeVisible();
    expect(screen.getByText('Only sampled rows are shown.')).toBeVisible();
    expect(screen.queryByText('Some columns are not included.')).toBeNull();
  });

  it('explains empty and schema-only datasets without a sample', () => {
    const { rerender } = render(
      <DatasetPreviewTable preview={{ ...dataset, rows: [], total_rows: 0 }} />,
    );
    expect(screen.getByText('Dataset is empty.')).toBeVisible();
    rerender(
      <DatasetPreviewTable
        preview={{
          ...dataset,
          rows: [],
          total_rows: undefined,
          total_columns: undefined,
          sample: { ...dataset.sample, rows_omitted: true },
        }}
      />,
    );
    expect(screen.getByText(/schema-only preview/)).toBeVisible();
    expect(screen.getByRole('status')).toHaveTextContent(
      'Showing 0 of unknown rows; 3 of unknown columns',
    );
    expect(within(screen.getByRole('table')).getAllByRole('row')).toHaveLength(1);
  });

  it('renders values as text and distinguishes null and empty strings', () => {
    const { container } = render(
      <DatasetPreviewTable
        preview={{ ...dataset, rows: [['<script>alert(1)</script>', null, '']] }}
      />,
    );
    expect(screen.getByText('<script>alert(1)</script>')).toBeVisible();
    expect(screen.getByText('null')).toBeVisible();
    expect(screen.getByText('""')).toBeVisible();
    expect(container.querySelector('script')).toBeNull();
  });

  it('renders model identity, recorded parameters, and structural facts separately', () => {
    render(<ModelPreviewSummary preview={model} />);
    expect(screen.getByRole('region', { name: 'Model preview' })).toBeVisible();
    expect(screen.getByText('xgboost')).toBeVisible();
    expect(screen.getByText('2.1.0')).toBeVisible();
    expect(screen.getByText('xgboost.XGBClassifier')).toBeVisible();
    expect(screen.getByRole('heading', { name: 'Recorded hyperparameters' })).toBeVisible();
    expect(screen.getByRole('heading', { name: 'Structural information' })).toBeVisible();
    expect(screen.getByText('max_depth')).toBeVisible();
    expect(screen.getByText('tree_count')).toBeVisible();
    const parameters = screen.getByRole('table', { name: 'Recorded hyperparameters' });
    const structure = screen.getByRole('table', { name: 'Structural information' });
    expect(within(parameters).getAllByRole('row')).toHaveLength(
      Object.keys(model.hyperparameters).length + 1,
    );
    expect(
      within(parameters)
        .getAllByRole('rowheader')
        .map((cell) => cell.textContent),
    ).toEqual(Object.keys(model.hyperparameters).sort());
    expect(within(parameters).getByText('"gbtree"')).toBeVisible();
    expect(within(structure).getAllByRole('row')).toHaveLength(
      Object.keys(model.structure).length + 1,
    );
    expect(screen.getByText('Weights are not included in the preview.')).toBeVisible();
    expect(screen.queryByText('Rows per page:')).toBeNull();
  });

  it('keeps every recorded model entry visible without spacer rows or pagination', () => {
    const hyperparameters = Object.fromEntries(
      Array.from({ length: 100 }, (_, index) => [`parameter_${index}`, index]),
    );
    render(
      <ModelPreviewSummary
        preview={{ ...model, framework: undefined, hyperparameters, structure: {} }}
      />,
    );
    const table = screen.getByRole('table', { name: 'Recorded hyperparameters' });
    expect(within(table).getAllByRole('row')).toHaveLength(101);
    expect(within(table).getAllByRole('rowheader')).toHaveLength(100);
    expect(screen.getByText('Not recorded.')).toBeVisible();
    expect(screen.getAllByText('Not recorded')).toHaveLength(2);
  });
});
