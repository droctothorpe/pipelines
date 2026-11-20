# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Nullable raw-container argv without Python in the user image."""

import base64
import json

import pytest

from e2e import support
from e2e.pipelines.container_optional_inputs import pipeline


def argv(done, name):
    output = support.task_output(support.task(done, name), 'report')
    lines = output.splitlines()
    actual = [base64.b64decode(line[1:]).decode() for line in lines[1:]]
    assert int(lines[0]) == len(actual)
    return actual


@pytest.mark.parametrize(
    'value, values',
    [
        pytest.param(None, [1, 2], marks=pytest.mark.smoke, id='absent'),
        pytest.param('', [1, 2], marks=pytest.mark.smoke, id='empty'),
        pytest.param('null', [1, 2], marks=pytest.mark.full, id='literal-null'),
        pytest.param(
            'quote " slash \\ braces {{x}}\nend',
            [1, 2],
            marks=pytest.mark.full,
            id='quoting',
        ),
        pytest.param(None, [], marks=pytest.mark.full, id='empty-list'),
    ],
)
def test_if_present_argv_matches_stock(client, record, value, values):
    arguments = {
        'values': values,
        **({} if value is None else {'value': value}),
    }
    submitted, done = support.run_pipeline(
        client, pipeline, arguments, timeout=300
    )
    assert done.state == 'SUCCEEDED', support.failures(done)
    actual = argv(done, 'capture')
    expected = (
        ['--absent', 'value=absent']
        if value is None
        else ['--value', value, 'value=' + value]
    )
    assert actual == expected, (actual, expected)
    staged = argv(done, 'capture-list')
    if values:
        assert staged[0] == '--datasets'
        artifacts = json.loads(staged[1])
        assert [item['metadata']['value'] for item in artifacts] == values
        assert all(
            item['uri'].startswith('s3://')
            and item['customPath'].startswith('/tmp/kfp/artifact-lists/')
            for item in artifacts
        )
        tail = staged[2:]
    else:
        assert staged[0] == '--no-datasets'
        tail = staged[1:]
    assert tail == (['--absent'] if value is None else ['--value', value])
    record(run_id=submitted.run_id, value=value, argv=actual, state=done.state)
