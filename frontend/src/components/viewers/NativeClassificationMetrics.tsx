// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import { useMemo } from 'react';
import { padding } from 'src/Css';
import Banner from 'src/components/Banner';
import { classificationMetrics } from 'src/lib/NativeMetrics';
import ConfusionMatrix from './ConfusionMatrix';
import ROCCurve from './ROCCurve';

export function NativeClassificationMetrics({
  metadata,
  name,
}: {
  metadata: Record<string, unknown>;
  name: string;
}) {
  const result = useMemo(() => classificationMetrics(metadata, name), [metadata, name]);
  return (
    <>
      {result.errors.map((error, index) => (
        <Banner
          key={index}
          mode='error'
          message='Invalid classification metrics artifact.'
          additionalInfo={error}
        />
      ))}
      {!!result.roc.length && (
        <div className={padding(40, 'lrt')}>
          <div className={padding(40, 'b')}>
            <h3>ROC Curve</h3>
          </div>
          <ROCCurve
            configs={result.roc}
            labels={result.labels}
            forceLegend={result.roc.length > 1}
            responsive
          />
        </div>
      )}
      {result.matrices.map((matrix, index) => (
        <div key={index} className={padding(40)}>
          <h3>Confusion Matrix: {matrix.name}</h3>
          <ConfusionMatrix configs={[matrix.config]} />
        </div>
      ))}
      {!result.errors.length && !result.roc.length && !result.matrices.length && (
        <Banner mode='info' message='There is no metrics artifact available in this step.' />
      )}
    </>
  );
}
