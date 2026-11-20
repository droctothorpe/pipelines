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
    for artifact in artifacts:
        assert (
            's3://' + artifact['s3']['bucket'] + '/' + artifact['s3']['key']
            in uris
        )
    record(run_id=submitted.run_id, root=root, state=done.state)
