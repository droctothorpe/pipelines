# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Unchanged SDK code runs twice: cold, then with default caching."""

from uuid import uuid4

import pytest

from e2e import support
from e2e.pipelines.default_pipeline import pipeline


@pytest.mark.smoke
def test_default_pipeline_runs_unchanged(client, record):
    value = int(uuid4().hex[:7], 16)
    for index in range(2):
        submitted, done = support.run_pipeline(
            client, pipeline, {'value': value}
        )
        assert done.state == 'SUCCEEDED', support.failures(done)
        assert (
            support.task_output(support.task(done, 'consume'))
            == 'unchanged-sdk-works'
        )
        if index:
            assert support.task(done, 'prepare').state == 'CACHED'
        record(run_id=submitted.run_id, state=done.state, iteration=index)
