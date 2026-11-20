# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Scalar and artifact OneOf across If/Elif/Else."""

import pytest

from e2e import support
from e2e.pipelines.oneof import pipeline


@pytest.mark.parametrize(
    'choice, expected',
    [
        pytest.param(0, 3, marks=pytest.mark.full, id='if'),
        pytest.param(1, 5, marks=pytest.mark.smoke, id='elif'),
        pytest.param(2, 7, marks=pytest.mark.full, id='else'),
    ],
)
def test_oneof_selects_the_taken_branch(client, record, choice, expected):
    submitted, done = support.run_pipeline(
        client, pipeline, {'choice': choice, 'expected': expected}, timeout=300
    )
    assert done.state == 'SUCCEEDED', support.failures(done)
    record(run_id=submitted.run_id, choice=choice, state=done.state)
