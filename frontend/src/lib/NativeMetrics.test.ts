// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import { expect, it } from 'vitest';
import { classificationMetrics } from './NativeMetrics';

const metadata = {
  confidenceMetrics: [{ confidenceThreshold: 0.5, falsePositiveRate: 0.1, recall: 0.9 }],
  confusionMatrix: {
    annotationSpecs: [{ displayName: 'negative' }, { displayName: 'positive' }],
    rows: [{ row: [3, 1] }, { row: [1, 5] }],
  },
};
it('adapts native metadata to the stock ROC and confusion-matrix viewers', () => {
  const result = classificationMetrics(metadata, 'metrics');
  expect(result.errors).toEqual([]);
  expect(result.roc[0].data[0]).toEqual({ label: '0.5', x: 0.1, y: 0.9 });
  expect(result.matrices[0].config.data).toEqual([
    [3, 1],
    [1, 5],
  ]);
  expect(result.matrices[0].config.labels).toEqual(['negative', 'positive']);
});
it('preserves slice labels', () => {
  const result = classificationMetrics(
    { evaluationSlices: [{ slice: 'test', sliceClassificationMetrics: metadata }] },
    'metrics',
  );
  expect(result.labels).toEqual(['test']);
  expect(result.matrices[0].name).toBe('test');
});
it('reports malformed structures rather than drawing misleading metrics', () => {
  const result = classificationMetrics(
    {
      ...metadata,
      confidenceMetrics: [{ recall: 'bad' }],
      confusionMatrix: { annotationSpecs: [{ displayName: 'a' }], rows: [{ row: [1, 2] }] },
    },
    'metrics',
  );
  expect(result.errors).toHaveLength(2);
  expect(result.roc).toEqual([]);
  expect(result.matrices).toEqual([]);
});
