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
