// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import type { ConfusionMatrixConfig } from 'src/components/viewers/ConfusionMatrix';
import type { ROCCurveConfig } from 'src/components/viewers/ROCCurve';
import { PlotType } from 'src/components/viewers/Viewer';

const record = (value: unknown): value is Record<string, unknown> =>
  !!value && typeof value === 'object' && !Array.isArray(value);
const number = (value: unknown): value is number =>
  typeof value === 'number' && Number.isFinite(value);

export function classificationMetrics(metadata: Record<string, unknown>, name: string) {
  const roc: ROCCurveConfig[] = [],
    labels: string[] = [],
    errors: string[] = [];
  const matrices: Array<{ name: string; config: ConfusionMatrixConfig }> = [];
  const slices = Array.isArray(metadata.evaluationSlices)
    ? metadata.evaluationSlices
    : [{ slice: name, sliceClassificationMetrics: metadata }];
  for (const slice of slices) {
    if (
      !record(slice) ||
      typeof slice.slice !== 'string' ||
      !record(slice.sliceClassificationMetrics)
    ) {
      errors.push('Invalid classification metrics slice.');
      continue;
    }
    const value = slice.sliceClassificationMetrics;
    const confidence = value.confidenceMetrics;
    if (confidence !== undefined) {
      if (
        !Array.isArray(confidence) ||
        !confidence.every(
          (point) =>
            record(point) &&
            number(point.confidenceThreshold) &&
            number(point.falsePositiveRate) &&
            number(point.recall),
        )
      ) {
        errors.push(
          `${slice.slice}: confidenceMetrics must contain numeric confidenceThreshold, falsePositiveRate and recall fields.`,
        );
      } else {
        roc.push({
          type: PlotType.ROC,
          data: confidence.map((point) => ({
            label: String(point.confidenceThreshold),
            x: point.falsePositiveRate as number,
            y: point.recall as number,
          })),
        });
        labels.push(slice.slice);
      }
    }
    const matrix = value.confusionMatrix;
    if (matrix !== undefined) {
      if (
        !record(matrix) ||
        !Array.isArray(matrix.annotationSpecs) ||
        !Array.isArray(matrix.rows) ||
        matrix.annotationSpecs.length !== matrix.rows.length ||
        !matrix.annotationSpecs.every(
          (category) => record(category) && typeof category.displayName === 'string',
        ) ||
        !matrix.rows.every(
          (row) =>
            record(row) &&
            Array.isArray(row.row) &&
            row.row.length === (matrix.rows as unknown[]).length &&
            row.row.every(number),
        )
      ) {
        errors.push(
          `${slice.slice}: confusionMatrix must be square with category labels and finite numeric cells.`,
        );
      } else {
        matrices.push({
          name: slice.slice,
          config: {
            type: PlotType.CONFUSION_MATRIX,
            axes: ['True label', 'Predicted label'],
            labels: matrix.annotationSpecs.map((category) => category.displayName),
            data: matrix.rows.map((row) => row.row),
          },
        });
      }
    }
  }
  return { roc, labels, matrices, errors };
}
