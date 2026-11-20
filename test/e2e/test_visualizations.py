# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Metric and Markdown artifacts produced the stock way; the browser smokes
read the resulting runs."""

import pytest

from e2e import support
from e2e.pipelines.visualizations import (
    classification_pipeline,
    markdown_pipeline,
)


@pytest.mark.full
@pytest.mark.parametrize(
    'function, task_name, artifact',
    [
        (classification_pipeline, 'evaluate', 'metrics'),
        (markdown_pipeline, 'report', 'document'),
    ],
    ids=['classification-metrics', 'markdown'],
)
def test_visualization_artifacts_are_recorded(
    client, record, function, task_name, artifact
):
    submitted, done = support.run_pipeline(client, function, timeout=300)
    assert done.state == 'SUCCEEDED', support.failures(done)
    produced = support.task(done, task_name).outputs.artifacts
    assert any(a.artifact_key == artifact for a in produced), produced
    record(run_id=submitted.run_id, pipeline=function.name, state=done.state)
