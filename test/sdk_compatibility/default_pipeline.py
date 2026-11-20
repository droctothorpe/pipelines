# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Run ordinary SDK code against a configured native installation.

Set KFP_TEST_TOKEN; optionally set KFP_TEST_HOST and KFP_TEST_NAMESPACE.
This creates two named runs and retains their data for inspection. It supplies
no native compiler options, custom image, or caching workaround.
"""

import json
import os
from uuid import uuid4

import kfp
from kfp import dsl


@dsl.component
def prepare(value: int, dataset: dsl.Output[dsl.Dataset]) -> int:
    from pathlib import Path

    Path(dataset.path).write_text(str(value))
    dataset.metadata['value'] = value
    return value + 1


@dsl.component
def consume(dataset: dsl.Input[dsl.Dataset], expected: int) -> str:
    from pathlib import Path

    assert int(Path(dataset.path).read_text()) + 1 == expected
    assert dataset.metadata['value'] + 1 == expected
    return 'unchanged-sdk-works'


@dsl.pipeline(name='sdk-default-compatibility')
def pipeline(value: int):
    task = prepare(value=value)
    consume(dataset=task.outputs['dataset'], expected=task.outputs['Output'])


if __name__ == '__main__':
    namespace = os.environ.get('KFP_TEST_NAMESPACE', 'kfp-argo')
    client = kfp.Client(
        host=os.environ.get('KFP_TEST_HOST', 'http://127.0.0.1:3003'),
        namespace=namespace,
        existing_token=os.environ['KFP_TEST_TOKEN'],
    )
    value = int(uuid4().hex[:7], 16)
    report = []
    for index in range(2):
        result = client.create_run_from_pipeline_func(
            pipeline,
            arguments={'value': value},
            run_name=f'SDK default compatibility {value} {index}',
            experiment_name='SDK backwards compatibility',
            namespace=namespace,
        )
        completed = result.wait_for_run_completion(timeout=600)
        assert completed.state == 'SUCCEEDED', completed.to_dict()
        report.append({'run_id': result.run_id, 'state': completed.state})
    print(json.dumps(report, indent=2))
