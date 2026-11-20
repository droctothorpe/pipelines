# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""The stock kube_context connection interface authenticates directly against
Kubernetes.

Needs KFP_TEST_CONTEXT and a kubeconfig; never prints credentials or
touches the user's SDK context file.
"""

import kfp
import pytest

from e2e import support
from e2e.pipelines.default_pipeline import pipeline


@pytest.mark.full
def test_kube_context_client_lists_and_runs(
    settings, record, tmp_path, monkeypatch
):
    if not settings.context:
        pytest.skip('KFP_TEST_CONTEXT is not set')
    monkeypatch.setattr(
        kfp.Client, '_LOCAL_KFP_CONTEXT', str(tmp_path / 'context.json')
    )
    client = kfp.Client(
        kube_context=settings.context,
        namespace=settings.namespace,
        healthz_max_attempts=1,
        existing_token=settings.token,
    )
    listing = client.list_experiments(namespace=settings.namespace)
    assert listing.total_size >= 0
    submitted, done = support.run_pipeline(
        client, pipeline, {'value': 2}, timeout=300
    )
    assert done.state == 'SUCCEEDED', support.failures(done)
    record(run_id=submitted.run_id, experiments=listing.total_size)
