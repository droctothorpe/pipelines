# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Run unchanged ClassificationMetrics logging without writing artifact files."""

import json
import os
from uuid import uuid4

import kfp
from kfp import dsl


@dsl.component
def evaluate(metrics: dsl.Output[dsl.ClassificationMetrics]):
    metrics.log_confusion_matrix(['negative', 'positive'], [[3, 1], [1, 5]])
    metrics.log_roc_curve([0.0, 0.1, 1.0], [0.0, 0.9, 1.0], [1.0, 0.5, 0.0])


@dsl.pipeline(name='classification-metrics-compatibility')
def pipeline():
    evaluate()


if __name__ == '__main__':
    namespace = os.environ.get('KFP_TEST_NAMESPACE', 'kfp-argo')
    client = kfp.Client(
        host=os.environ.get('KFP_TEST_HOST', 'http://127.0.0.1:3003'),
        namespace=namespace,
        existing_token=os.environ['KFP_TEST_TOKEN'],
    )
    run = client.create_run_from_pipeline_func(
        pipeline,
        arguments={},
        run_name='Classification compatibility ' + uuid4().hex[:8],
        experiment_name='SDK backwards compatibility',
        namespace=namespace,
    )
    completed = run.wait_for_run_completion(timeout=300)
    assert completed.state == 'SUCCEEDED', completed.to_dict()
    print(json.dumps({'run_id': run.run_id}))
