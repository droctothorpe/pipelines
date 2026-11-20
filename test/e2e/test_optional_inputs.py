# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""None, literal null and empty strings across pipeline and condition
boundaries, for Python components."""

import json

import pytest
from kfp import dsl

from e2e import support


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
    with dsl.If(value == None):  # noqa: E711
        missing = forwarded(expected='null')
    with dsl.Else():
        present = fallback(value=value)
        check(expected=expected, value=value)
        interpolation(value=f'prefix:{value}', original=value)
    check(expected=expected, value=dsl.OneOf(missing.output, present.output))


@pytest.mark.parametrize(
    'value',
    [
        pytest.param(None, marks=pytest.mark.smoke, id='none'),
        pytest.param('null', marks=pytest.mark.full, id='literal-null'),
        pytest.param('', marks=pytest.mark.full, id='empty'),
        pytest.param(
            'quoted " value }} and \\', marks=pytest.mark.full, id='quoting'
        ),
    ],
)
def test_optional_values_keep_identity(client, record, value):
    arguments = {'expected': json.dumps(value)}
    if value is not None:
        arguments['value'] = value
    submitted, done = support.run_pipeline(
        client, pipeline, arguments, timeout=300
    )
    assert done.state == 'SUCCEEDED', support.failures(done)
    assert done.runtime_config.parameters['value'] == value
    assert support.task_output(support.task(done, 'fallback')) == (
        'fallback' if value is None else value
    )
    record(run_id=submitted.run_id, value=value, state=done.state)
