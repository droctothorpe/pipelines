# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""None, literal null and empty strings across pipeline/condition boundaries."""

import json
import os
from uuid import uuid4

import kfp
from kfp import dsl


@dsl.component
def check(expected: str, value: str = None) -> str:
    import json

    actual = json.dumps(value)
    assert actual == expected, (actual, expected)
    return actual


@dsl.component
def fallback(value: str = 'fallback') -> str:
    return value


@dsl.component
def interpolation(value: str, original: str) -> str:
    assert value == 'prefix:' + original, (value, original)
    return value


@dsl.pipeline
def forwarded(expected: str, value: str = None) -> str:
    check(expected=expected, value=value)
    return value


@dsl.pipeline(name='optional-input-compatibility')
def pipeline(expected: str = 'null', value: str = None):
    result = forwarded(expected=expected, value=value)
    check(expected=expected, value=result.output)
    fallback(value=value)
    with dsl.If(value == None):
        missing = forwarded(expected='null')
    with dsl.Else():
        present = fallback(value=value)
        check(expected=expected, value=value)
        interpolation(value=f'prefix:{value}', original=value)
    check(expected=expected, value=dsl.OneOf(missing.output, present.output))


if __name__ == '__main__':
    namespace = os.environ.get('KFP_TEST_NAMESPACE', 'kfp-argo')
    client = kfp.Client(
        host=os.environ.get('KFP_TEST_HOST', 'http://127.0.0.1:3003'),
        namespace=namespace,
        existing_token=os.environ['KFP_TEST_TOKEN'],
    )
    report = []
    for value in (None, 'null', '', 'quoted " value }} and \\'):
        arguments = {'expected': json.dumps(value)}
        if value is not None:
            arguments['value'] = value
        run = client.create_run_from_pipeline_func(
            pipeline,
            arguments=arguments,
            run_name='Optional input ' + uuid4().hex[:8],
            experiment_name='SDK backwards compatibility',
            namespace=namespace,
        )
        done = run.wait_for_run_completion(timeout=240)
        assert done.state == 'SUCCEEDED', [
            (t.display_name, t.state, t.lifecycle_message)
            for t in (done.tasks or [])
        ]
        assert done.runtime_config.parameters['value'] == value
        task = next(t for t in done.tasks if t.display_name == 'fallback')
        assert next(
            p.value
            for p in task.outputs.parameters
            if p.parameter_key == 'Output'
        ) == ('fallback' if value is None else value)
        report.append(
            {'run_id': run.run_id, 'value': value, 'state': done.state}
        )
    print(json.dumps(report, indent=2))
