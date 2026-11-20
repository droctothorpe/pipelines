# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0

import json

import pytest

from kfp.dsl import argo_staging


def identity(uri='s3://data/original-run/model'):
    return {
        'schema': 'kfp-argo/v1',
        'type': 'system.Dataset@0.0.1',
        'port': 'data',
        'uri': uri,
        'metadata': {'value': 7},
        'producer': {
            'run': 'original-run',
            'task': 'original-pod',
            'namespace': 'team',
        },
    }


def test_prepare_flattens_metadata_and_preserves_cached_identity_and_order():
    first, second = identity(), identity("s3://data/a path/quoted'model")
    value = json.dumps(
        [json.dumps([json.dumps(first)]), json.dumps([json.dumps(second)])]
    )
    repository = {
        's3': {
            'endpoint': 'storage:9000',
            'insecure': True,
            'accessKeySecret': {'name': 'storage', 'key': 'access'},
        }
    }
    template, manifest = argo_staging.prepare(
        [{'name': 'kfp-meta-models', 'value': value}],
        {'models': 'system.Dataset@0.0.1'},
        repository,
    )
    assert (
        template['inputs']['artifacts'][1]['s3']['key'] == "a path/quoted'model"
    )
    assert (
        template['inputs']['artifacts'][0]['s3']['accessKeySecret']['name']
        == 'storage'
    )
    assert [r['identity'] for r in manifest['inputs']['models']] == [
        first,
        second,
    ]
    assert [r['path'] for r in manifest['inputs']['models']] == [
        argo_staging.DATA_ROOT + '/artifact-0',
        argo_staging.DATA_ROOT + '/artifact-1',
    ]
    assert 'accessKeySecret' not in json.dumps(manifest), (
        'No credential config in the main-container volume'
    )


def test_minimal_cached_identity_loads_its_metadata_companion():
    cached = identity('s3://data/original-run/original-pod/data')
    cached.pop('metadata')
    template, manifest = argo_staging.prepare(
        [{'name': 'kfp-meta-models', 'value': json.dumps([cached])}],
        {'models': 'system.Dataset@0.0.1'},
        {'s3': {'endpoint': 'storage'}},
    )
    assert (
        template['inputs']['artifacts'][0]['s3']['key']
        == 'original-run/original-pod/metadata/data.json'
    )
    assert (
        manifest['inputs']['models'][0]['metadataPath']
        == argo_staging.DATA_ROOT + '/metadata-0'
    )
    cached['uri'] = 's3://data/explicit-user-uri'
    cached['metadataUri'] = (
        's3://data/prefix/original-run/original-pod/metadata/data.json'
    )
    template, _ = argo_staging.prepare(
        [{'name': 'kfp-meta-models', 'value': json.dumps([cached])}],
        {'models': 'system.Dataset@0.0.1'},
        {'s3': {'endpoint': 'storage'}},
    )
    assert template['inputs']['artifacts'][0]['s3']['key'].startswith('prefix/')


def test_raw_arguments_preserve_proto_shape_empty_lists_and_marker_literals():
    item = identity()
    item['metadata']['literal'] = '__KFP_LIST_empty__'
    manifest = {
        'inputs': {
            'data': [{'identity': item, 'path': '/tmp/staged'}],
            'empty': [],
        }
    }
    arguments, summary = argo_staging.expand_raw_arguments(
        manifest,
        ['__KFP_LIST_data__', '__KFP_LIST_empty__'],
        {'inputs': [], 'artifacts': []},
    )
    artifact = json.loads(arguments[0])[0]
    assert artifact['uri'] == item['uri']
    assert artifact['customPath'] == '/tmp/staged'
    assert artifact['type'] == {
        'schemaTitle': 'system.Dataset',
        'schemaVersion': '0.0.1',
    }
    assert artifact['metadata']['literal'] == '__KFP_LIST_empty__'
    assert json.loads(arguments[1]) == []
    assert summary['inputs'][0]['producer'] == item['producer']


def test_artifact_iteration_requires_one_identity_and_exposes_its_path():
    item = identity()
    template, manifest = argo_staging.prepare(
        [{'name': 'kfp-meta-data', 'value': json.dumps(item)}],
        {'data': {'type': 'system.Dataset@0.0.1', 'single': True}},
        {'s3': {'endpoint': 'storage'}},
    )
    assert manifest['singles'] == ['data']
    assert len(template['inputs']['artifacts']) == 1
    arguments, summary = argo_staging.expand_raw_arguments(
        manifest, ['__KFP_PATH_data__'], {'inputs': [], 'artifacts': []}
    )
    assert arguments == [argo_staging.DATA_ROOT + '/artifact-0']
    assert summary['inputs'][0]['port'] == 'data'
    with pytest.raises(ValueError, match='exactly one'):
        argo_staging.prepare(
            [{'name': 'kfp-meta-data', 'value': json.dumps([item, item])}],
            {'data': {'type': 'system.Dataset@0.0.1', 'single': True}},
            {'s3': {'endpoint': 'storage'}},
        )


def test_empty_collection_is_an_empty_list():
    template, manifest = argo_staging.prepare(
        [{'name': 'kfp-meta-models', 'value': '[]'}],
        {'models': 'system.Dataset@0.0.1'},
        {},
    )
    assert template['inputs']['artifacts'] == []
    assert manifest['inputs']['models'] == []


@pytest.mark.parametrize(
    'uri',
    [
        'file:///etc/passwd',
        's3://user:password@bucket/key',
        's3://bucket/key?token=abc',
        'ftp://host/file',
    ],
)
def test_stager_rejects_unsupported_or_credential_bearing_uris(uri):
    with pytest.raises(ValueError):
        argo_staging.location(uri, {'s3': {'endpoint': 'storage'}})


def test_http_never_inherits_storage_credentials():
    repository = {
        's3': {'accessKeySecret': {'name': 'storage', 'key': 'access'}}
    }
    assert argo_staging.location('https://example.test/data', repository) == {
        'http': {'url': 'https://example.test/data'}
    }


def test_gcs_uses_its_own_provider_configuration():
    repository = {
        'gcs': {'serviceAccountKeySecret': {'name': 'cloud', 'key': 'json'}}
    }
    assert argo_staging.location('gs://bucket/data', repository) == {
        'gcs': {
            'serviceAccountKeySecret': {'name': 'cloud', 'key': 'json'},
            'bucket': 'bucket',
            'key': 'data',
        }
    }
