# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Exercise scalar and artifact OneOf across If/Elif/Else on native Argo."""

import json
import os
from uuid import uuid4

import kfp
from kfp import dsl


@dsl.component
def produce(value: int, data: dsl.Output[dsl.Dataset]) -> int:
    from pathlib import Path

    Path(data.path).write_text(str(value))
    data.metadata['value'] = value
    return value


@dsl.component
def check(value: int, data: dsl.Input[dsl.Dataset], expected: int) -> int:
    from pathlib import Path

    assert value == expected
    assert int(Path(data.path).read_text()) == expected
    assert data.metadata['value'] == expected
    return value


@dsl.pipeline(name='oneof-user-program')
def pipeline(choice: int, expected: int) -> int:
    with dsl.If(choice == 0):
        first = produce(value=3)
    with dsl.Elif(choice == 1):
        second = produce(value=5)
    with dsl.Else():
        third = produce(value=7)
    return check(
        value=dsl.OneOf(
            first.outputs['Output'],
            second.outputs['Output'],
            third.outputs['Output'],
        ),
        data=dsl.OneOf(
            first.outputs['data'], second.outputs['data'], third.outputs['data']
        ),
        expected=expected,
    ).output


if __name__ == '__main__':
    client = kfp.Client(
        host=os.environ.get('KFP_TEST_HOST', 'http://127.0.0.1:3003'),
        namespace=os.environ.get('KFP_TEST_NAMESPACE', 'kfp-argo'),
        existing_token=os.environ['KFP_TEST_TOKEN'],
    )
    report = []
    for choice, expected in enumerate([3, 5, 7]):
        run = client.create_run_from_pipeline_func(
            pipeline,
            arguments={'choice': choice, 'expected': expected},
            run_name='OneOf compatibility ' + uuid4().hex[:8],
            experiment_name='SDK backwards compatibility',
            namespace=client.get_user_namespace(),
        )
        completed = run.wait_for_run_completion(timeout=300)
        assert completed.state == 'SUCCEEDED', completed.to_dict()
        report.append(
            {'choice': choice, 'expected': expected, 'run_id': run.run_id}
        )
    print(json.dumps(report, indent=2))
