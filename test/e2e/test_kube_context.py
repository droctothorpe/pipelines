# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""The stock kube_context connection interface authenticates directly against
Kubernetes, and reaches the archive through Argo Server with the same token.

Needs KFP_TEST_CONTEXT and a kubeconfig; KFP_TEST_ARGO_SERVER enables
the archive half. Never prints credentials or touches the user's SDK
context file.
"""

import time
import warnings

import kfp
import pytest

from e2e import support
from e2e.pipelines.default_pipeline import pipeline

ARCHIVED = 'workflows.argoproj.io/workflow-archiving-status'


def _client(settings, tmp_path, monkeypatch, **options):
    monkeypatch.setattr(
        kfp.Client, '_LOCAL_KFP_CONTEXT', str(tmp_path / 'context.json')
    )
    return kfp.Client(
        kube_context=settings.context,
        namespace=settings.namespace,
        healthz_max_attempts=1,
        existing_token=settings.token,
        **options,
    )


@pytest.mark.full
def test_kube_context_client_lists_and_runs(
    settings, record, tmp_path, monkeypatch
):
    if not settings.context:
        pytest.skip('KFP_TEST_CONTEXT is not set')
    monkeypatch.delenv('ARGO_SERVER', raising=False)
    client = _client(settings, tmp_path, monkeypatch)
    # Without an Argo Server address the archive is unreachable through the
    # Kubernetes API; listings warn once and still cover the live inventory.
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        listing = client.list_experiments(namespace=settings.namespace)
    assert listing.total_size >= 0
    submitted, done = support.run_pipeline(
        client, pipeline, {'value': 2}, timeout=300
    )
    assert done.state == 'SUCCEEDED', support.failures(done)
    with warnings.catch_warnings(record=True) as later:
        warnings.simplefilter('always')
        runs = client.list_runs(
            namespace=settings.namespace,
            page_size=20,
            sort_by='created_at desc',
        )
    assert submitted.run_id in {run.run_id for run in runs.runs}
    record(
        run_id=submitted.run_id,
        experiments=listing.total_size,
        archive_warning=any(
            'Archived runs' in str(warning.message)
            for warning in caught + later
        ),
    )


@pytest.mark.full
def test_kube_context_client_reads_the_archive_from_argo_server(
    settings, record, tmp_path, monkeypatch
):
    """A run whose live workflow is gone exists only in Argo's archive; the
    direct client reads it from Argo Server with its Kubernetes token, so the
    UI proxy is not part of the SDK path."""
    if not settings.context:
        pytest.skip('KFP_TEST_CONTEXT is not set')
    if not settings.argo_server:
        pytest.skip('KFP_TEST_ARGO_SERVER is not set')
    monkeypatch.setenv('ARGO_INSECURE_SKIP_VERIFY', 'true')
    client = _client(
        settings, tmp_path, monkeypatch, argo_server=settings.argo_server
    )
    transport = client._run_api.transport
    assert transport.argo_server == settings.argo_server.rstrip('/')
    submitted, done = support.run_pipeline(
        client, pipeline, {'value': 3}, timeout=300
    )
    assert done.state == 'SUCCEEDED', support.failures(done)
    metadata = done.pipeline_spec['metadata']
    path = (
        f'/kubernetes/apis/argoproj.io/v1alpha1/namespaces/{metadata["namespace"]}'
        f'/workflows/{metadata["name"]}'
    )
    deadline = time.time() + 120
    while True:
        labels = transport.request('GET', path)['metadata'].get('labels', {})
        if labels.get(ARCHIVED) == 'Archived':
            break
        assert time.time() < deadline, f'not archived yet: {labels}'
        time.sleep(2)
    transport.request('DELETE', path)
    with warnings.catch_warnings():
        # The archive must be read, not skipped with the C18 warning.
        warnings.filterwarnings('error', message='Archived runs')
        archived = client.get_run(submitted.run_id)
        runs = client.list_runs(
            namespace=settings.namespace,
            page_size=50,
            sort_by='created_at desc',
        )
    assert archived.state == 'SUCCEEDED'
    assert submitted.run_id in {run.run_id for run in runs.runs}
    record(run_id=submitted.run_id, argo_server=True)
