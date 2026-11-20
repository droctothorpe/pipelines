# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Upload, version, run and list through the public client; the browser smoke
reuses the same module to create what it inspects."""

import pytest

from e2e.pipelines.ui_interop import create


@pytest.mark.smoke
def test_upload_version_and_run_round_trip(client, namespace, record):
    created = create(client, namespace)
    runs = client.list_runs(experiment_id=created['experiment_id']).runs
    assert [run.run_id for run in runs] == [created['run_id']]
    versions = client.list_pipeline_versions(
        created['pipeline_id']
    ).pipeline_versions
    assert [v.pipeline_version_id for v in versions] == [created['version_id']]
    record(**created)
