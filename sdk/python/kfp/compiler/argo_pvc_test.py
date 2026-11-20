# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from kubernetes.client import ApiException

from kfp.compiler.argo_pvc import execute


@pytest.mark.parametrize('storage_class', [None, '', 'standard'])
def test_create_pvc_preserves_storage_class_and_source(storage_class):
    api = Mock()
    inputs = {
        'access_modes': ['ReadWriteOnce'],
        'size': '5Gi',
        'pvc_name_suffix': '-sample',
        'storage_class_name': storage_class,
        'data_source': {'kind': 'PersistentVolumeClaim', 'name': 'source'},
    }
    name = execute('create', inputs, 'team', api)
    assert name.endswith('-sample')
    namespace, claim = (
        api.create_namespaced_persistent_volume_claim.call_args.args
    )
    assert namespace == 'team'
    assert claim['spec']['dataSource'] == inputs['data_source']
    if storage_class is None:
        assert 'storageClassName' not in claim['spec']
    else:
        assert claim['spec']['storageClassName'] == storage_class


def test_existing_claim_is_not_modified_and_denial_is_not_hidden():
    api = Mock()
    values = {
        'access_modes': ['ReadWriteOnce'],
        'size': '5Gi',
        'pvc_name': 'existing',
    }
    api.create_namespaced_persistent_volume_claim.side_effect = ApiException(
        status=409
    )
    assert execute('create', values, 'team', api) == 'existing'
    assert len(api.mock_calls) == 1
    api.create_namespaced_persistent_volume_claim.side_effect = ApiException(
        status=403
    )
    with pytest.raises(ApiException):
        execute('create', values, 'team', api)


def test_delete_is_uid_safe_and_absence_is_idempotent():
    api = Mock()
    api.read_namespaced_persistent_volume_claim.return_value = SimpleNamespace(
        metadata=SimpleNamespace(uid='original')
    )
    execute('delete', {'pvc_name': 'claim'}, 'team', api)
    assert (
        api.delete_namespaced_persistent_volume_claim.call_args.kwargs[
            'body'
        ].preconditions.uid
        == 'original'
    )
    api.reset_mock()
    api.read_namespaced_persistent_volume_claim.side_effect = ApiException(
        status=404
    )
    execute('delete', {'pvc_name': 'claim'}, 'team', api)
    api.delete_namespaced_persistent_volume_claim.assert_not_called()
