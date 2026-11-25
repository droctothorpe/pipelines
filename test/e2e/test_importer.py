# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Importer metadata, payload staging and reimport versus cache reuse.

The imported object is produced by a first run, so no external URI is
needed.
"""

import pytest
from kfp import dsl

from e2e import support


@dsl.component
def write(rows: int, data: dsl.Output[dsl.Dataset]):
    from pathlib import Path

    Path(data.path).write_text(str(rows))


@dsl.pipeline(name='native-importer-source')
def source_pipeline(rows: int = 37):
    write(rows=rows).set_caching_options(False)


@dsl.component
def check(data: dsl.Input[dsl.Dataset], expected: int) -> int:
    from pathlib import Path

    assert int(Path(data.path).read_text()) == expected
    assert data.metadata['rows'] == expected
    assert data.metadata['description'] == 'Imported from ' + data.uri
    return expected


@dsl.pipeline(name='native-importer-user-program')
def pipeline(uri: str, rows: int = 37):
    imported = dsl.importer(
        artifact_uri=uri,
        artifact_class=dsl.Dataset,
        metadata={'rows': rows, 'description': f'Imported from {uri}'},
    )
    check(data=imported.output, expected=rows)


@dsl.pipeline(name='native-reimport-user-program')
def reimport_pipeline(uri: str, rows: int = 37):
    imported = dsl.importer(
        artifact_uri=uri,
        artifact_class=dsl.Dataset,
        reimport=True,
        metadata={'rows': rows, 'description': f'Imported from {uri}'},
    )
    check(data=imported.output, expected=rows)


@pytest.fixture(scope='module')
def dataset_uri(client):
    _, done = support.run_pipeline(client, source_pipeline, timeout=300)
    assert done.state == 'SUCCEEDED', support.failures(done)
    artifact = support.task(done, 'write').outputs.artifacts[0].artifacts[0]
    assert artifact.uri.startswith('s3://'), artifact
    return artifact.uri


@pytest.mark.full
@pytest.mark.parametrize(
    'function, reuse',
    [(pipeline, True), (reimport_pipeline, False)],
    ids=['cached', 'reimport'],
)
def test_importer_metadata_and_cache_choice(
    client, record, dataset_uri, function, reuse
):
    for iteration in range(2):
        submitted = support.submit(client, function, {'uri': dataset_uri})
        done, raw = support.wait_without_errors(
            client, submitted, 300, ('importer',)
        )
        assert done.state == 'SUCCEEDED', support.phases(raw)
        importer = support.node(raw, 'importer')
        assert importer['type'] == 'DAG'
        if iteration:
            assert (
                bool(importer.get('memoizationStatus', {}).get('hit')) is reuse
            )
            consumer = support.node(raw, 'check')
            assert (
                bool(consumer.get('memoizationStatus', {}).get('hit')) is reuse
            )
        record(run_id=submitted.run_id, reuse=reuse, iteration=iteration)


@dsl.component
def check_workspace(data: dsl.Input[dsl.Dataset], expected: int) -> str:
    from pathlib import Path

    assert data.path.startswith('/kfp-workspace/.artifacts/s3/'), data.path
    assert int(Path(data.path).read_text()) == expected
    assert not Path('/tmp/kfp/inputs/data').exists(), (
        'the payload must not be staged a second time'
    )
    assert data.metadata['_kfp_workspace'] is True, data.metadata
    assert data.metadata['rows'] == expected
    return data.path


@dsl.pipeline(
    name='native-importer-workspace',
    pipeline_config=dsl.PipelineConfig(
        workspace=dsl.WorkspaceConfig(
            size='1Mi',
            kubernetes=dsl.KubernetesWorkspaceConfig(
                pvcSpecPatch={
                    'accessModes': ['ReadWriteOnce'],
                    'storageClassName': 'standard',
                }
            ),
        )
    ),
)
def workspace_pipeline(uri: str, rows: int = 37):
    imported = dsl.importer(
        artifact_uri=uri,
        artifact_class=dsl.Dataset,
        download_to_workspace=True,
        metadata={'rows': rows},
    )
    check_workspace(data=imported.output, expected=rows)


@pytest.mark.full
def test_importer_downloads_into_the_workspace(client, record, dataset_uri):
    """C07: the payload lands at stock's workspace path once and the consumer
    reads it from the shared volume."""
    submitted, done = support.run_pipeline(
        client, workspace_pipeline, {'uri': dataset_uri}, timeout=300
    )
    raw = support.workflow(client, done)
    assert done.state == 'SUCCEEDED', support.phases(raw)
    path = support.node_output(support.node(raw, 'check-workspace'), 'Output')
    assert path == '/kfp-workspace/.artifacts/' + dataset_uri.replace(
        '://', '/', 1
    )
    pods = support.pods(client, raw)
    mounted = [
        p
        for p in pods
        if any(v['name'] == 'kfp-workspace' for v in p['spec']['volumes'])
    ]
    assert len(mounted) == 2, [p['metadata']['name'] for p in pods]
    record(run_id=submitted.run_id, path=path, pods=len(pods))
