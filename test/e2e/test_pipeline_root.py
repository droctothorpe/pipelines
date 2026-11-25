# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Public pipeline_root overrides land artifacts at the requested location."""

from uuid import uuid4

import pytest

from e2e import support
from e2e.pipelines.default_pipeline import pipeline


@pytest.mark.full
@pytest.mark.parametrize('suffix', ['normal', "quote' and space"])
def test_pipeline_root_override_controls_artifact_location(
    client, settings, record, suffix
):
    root = (
        settings.artifact_root
        + '/root-compat-'
        + uuid4().hex[:8]
        + '/'
        + suffix
    )
    submitted, done = support.run_pipeline(
        client,
        pipeline,
        {'value': 37},
        pipeline_root=root,
        enable_caching=False,
    )
    assert done.state == 'SUCCEEDED', support.failures(done)
    assert done.runtime_config.pipeline_root == root
    raw = support.workflow(client, done)
    uris = [
        parameter['value']
        for entry in support.nodes(raw)
        for parameter in entry.get('outputs', {}).get('parameters', [])
        if parameter['name'] == 'kfp-uri-dataset'
    ]
    assert uris and all(
        uri.startswith(root + '/' + submitted.run_id + '/') for uri in uris
    ), uris
    artifacts = [
        artifact
        for entry in support.nodes(raw)
        for artifact in entry.get('outputs', {}).get('artifacts', [])
        if artifact.get('name') == 'dataset'
    ]
    assert artifacts
    # Artifacts carry keys only; the bucket is the repository Argo resolved.
    assert support.repository_root(raw) == settings.artifact_root
    for artifact in artifacts:
        assert settings.artifact_root + '/' + artifact['s3']['key'] in uris, (
            artifact
        )
    record(run_id=submitted.run_id, root=root, state=done.state)


@pytest.mark.smoke
def test_runs_follow_the_namespace_artifact_repository(
    client, settings, record
):
    """No root in the package or the request: artifacts land in the Argo
    repository configured for the namespace, the run reports that root, and
    a root nothing serves is refused before anything is created."""
    from kfp.server_api import ApiException

    expected = support.namespace_root(client, settings.namespace)
    submitted, done = support.run_pipeline(
        client, pipeline, {'value': 41}, enable_caching=False
    )
    assert done.state == 'SUCCEEDED', support.failures(done)
    assert done.runtime_config.pipeline_root == expected
    raw = support.workflow(client, done)
    assert support.repository_root(raw) == expected
    assert 'artifactRepositoryRef' not in raw['spec']
    uris = [
        parameter['value']
        for entry in support.nodes(raw)
        for parameter in entry.get('outputs', {}).get('parameters', [])
        if parameter['name'] == 'kfp-uri-dataset'
    ]
    assert uris and all(
        uri.startswith(expected + '/' + submitted.run_id + '/') for uri in uris
    ), uris
    with pytest.raises(ApiException) as refused:
        support.submit(
            client,
            pipeline,
            {'value': 1},
            pipeline_root='s3://nowhere-' + submitted.run_id[:8],
        )
    assert refused.value.status == 400
    assert 'No artifact repository' in str(refused.value.reason)
    record(run_id=submitted.run_id, root=expected, refused='s3://nowhere')
