# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0

import pytest

from kfp.compiler import argo_artifacts

ENTRIES = {
    'default-v1': {
        's3': {'bucket': 'argo-artifacts', 'endpoint': 'minio:9000'}
    },
    'archive': {'s3': {'bucket': 'cold-storage', 'endpoint': 'minio:9000'}},
    'exports': {'gcs': {'bucket': 'exports'}},
    'empty': {},
    'plugin': {'plugin': {'name': 'test'}},
}


def package(**annotations):
    return {'metadata': {'annotations': annotations}}, {}


def test_compile_time_root_is_optional():
    assert argo_artifacts.root_annotations(None) == {
        argo_artifacts.ROOT: '',
        argo_artifacts.BUCKET: '',
        argo_artifacts.PREFIX: '',
        argo_artifacts.BINDING: 'v1',
    }
    assert argo_artifacts.root_annotations('gs://bucket/a/b/') == {
        argo_artifacts.ROOT: 'gs://bucket/a/b',
        argo_artifacts.BUCKET: 'bucket',
        argo_artifacts.PREFIX: 'a/b/',
        argo_artifacts.BINDING: 'v1',
    }
    with pytest.raises(ValueError):
        argo_artifacts.root_annotations('http://bucket/a')


def test_runs_bind_to_the_namespace_default_repository():
    manifest, spec = package(**{argo_artifacts.BINDING: 'v1'})
    assert (
        argo_artifacts.bind_root(manifest, spec, ENTRIES, 'default-v1')
        == 's3://argo-artifacts'
    )
    assert manifest['metadata']['annotations'][argo_artifacts.BUCKET] == (
        'argo-artifacts'
    )
    assert manifest['metadata']['annotations'][argo_artifacts.PREFIX] == ''
    assert 'artifactRepositoryRef' not in spec
    manifest, spec = package(**{argo_artifacts.BINDING: 'v1'})
    assert (
        argo_artifacts.bind_root(manifest, spec, ENTRIES, 'exports')
        == 'gs://exports'
    )


def test_explicit_roots_select_the_entry_serving_their_bucket():
    manifest, spec = package(**{argo_artifacts.BINDING: 'v1'})
    assert (
        argo_artifacts.bind_root(
            manifest, spec, ENTRIES, 'default-v1', 's3://cold-storage/team/x/'
        )
        == 's3://cold-storage/team/x'
    )
    assert spec['artifactRepositoryRef'] == {'key': 'archive'}
    assert manifest['metadata']['annotations'][argo_artifacts.PREFIX] == (
        'team/x/'
    )
    # The default entry needs no reference, and a stale one is dropped.
    spec['artifactRepositoryRef'] = {'key': 'archive'}
    argo_artifacts.bind_root(
        manifest, spec, ENTRIES, 'default-v1', 's3://argo-artifacts/y'
    )
    assert 'artifactRepositoryRef' not in spec
    # A compile-time root is a request like any other.
    manifest, spec = package(
        **argo_artifacts.root_annotations('gs://exports/p')
    )
    argo_artifacts.bind_root(
        manifest, spec, ENTRIES, 'default-v1', 'gs://exports/p'
    )
    assert spec['artifactRepositoryRef'] == {'key': 'exports'}


def test_unserved_or_missing_repositories_are_refused():
    manifest, spec = package(**{argo_artifacts.BINDING: 'v1'})
    with pytest.raises(ValueError, match='serves s3://elsewhere.*cold-storage'):
        argo_artifacts.bind_root(
            manifest, spec, ENTRIES, 'default-v1', 's3://elsewhere/x'
        )
    with pytest.raises(ValueError, match='Configure an Argo artifact'):
        argo_artifacts.bind_root(manifest, spec, {}, None)
    with pytest.raises(ValueError, match='repository plugin'):
        argo_artifacts.bind_root(manifest, spec, ENTRIES, 'plugin')
    with pytest.raises(ValueError, match='names no S3/GCS bucket'):
        argo_artifacts.bind_root(manifest, spec, ENTRIES, 'empty')


def test_hand_written_packages_are_left_alone_unless_a_root_is_requested():
    manifest, spec = package()
    assert (
        argo_artifacts.bind_root(manifest, spec, ENTRIES, 'default-v1') is None
    )
    assert manifest['metadata']['annotations'] == {}
    with pytest.raises(ValueError, match='Recompile'):
        argo_artifacts.bind_root(
            manifest, spec, ENTRIES, 'default-v1', 's3://argo-artifacts/x'
        )
