# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""None, literal null and empty strings across pipeline and condition
boundaries, for Python components."""

import json

import pytest

from e2e import support
from e2e.pipelines.optional_inputs import pipeline, root_artifact_pipeline


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


@pytest.mark.smoke
def test_optional_root_artifact_input_is_absent(client, record):
    submitted, done = support.run_pipeline(client, root_artifact_pipeline, {})
    raw = support.workflow(client, done)
    assert done.state == 'SUCCEEDED', support.failures(done)
    assert support.node_output(support.node(raw, 'describe')) == 'absent'
    record(run_id=submitted.run_id, model='absent')
