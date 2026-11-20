# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0

import json
from unittest.mock import Mock

import pytest

from kfp.client._artifact_repository import prepare_staging
from kfp.compiler.argo_artifact_lists import add_staging
from kfp.server_api.exceptions import ApiException


def spec():
    template = {'name': 'consumer', 'container': {'image': 'user-image'}}
    add_staging(template, {'values': 'system.Dataset@0.0.1'})
    return {'templates': [template]}


def test_ordinary_runs_make_no_repository_requests():
    read = Mock()
    prepare_staging({'templates': []}, read)
    read.assert_not_called()


def test_namespace_default_uses_selectors_not_secret_reads():
    read = Mock(
        return_value={
            'metadata': {
                'annotations': {
                    'workflows.argoproj.io/default-artifact-repository': 'default'
                }
            },
            'data': {
                'default': json.dumps(
                    {
                        's3': {
                            'endpoint': 'minio:9000',
                            'accessKeySecret': {
                                'name': 'storage',
                                'key': 'access',
                            },
                        }
                    }
                )
            },
        }
    )
    workflow = spec()
    prepare_staging(workflow, read)
    read.assert_called_once_with('artifact-repositories')
    assert (
        workflow['templates'][0]['volumes'][-1]['secret']['secretName']
        == 'storage'
    )
    assert all(
        v['name'] != workflow['templates'][0]['volumes'][-1]['name']
        for v in workflow['templates'][0]['container']['volumeMounts']
    )


def test_forbidden_repository_read_does_not_fall_back_to_another_identity():
    read = Mock(side_effect=ApiException(status=403, reason='Forbidden'))
    with pytest.raises(ApiException) as error:
        prepare_staging(spec(), read)
    assert error.value.status == 403
    read.assert_called_once_with('artifact-repositories')


def test_explicit_repository_reference_does_not_use_a_different_default():
    workflow = spec()
    workflow['artifactRepositoryRef'] = {
        'configMap': 'custom-repositories',
        'key': 'missing',
    }
    read = Mock(return_value={'metadata': {}, 'data': {'default': '{}'}})
    with pytest.raises(
        ValueError, match='Configure an Argo artifact repository'
    ):
        prepare_staging(workflow, read)
    read.assert_called_once_with('custom-repositories')
