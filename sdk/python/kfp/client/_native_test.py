# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Native backend behaviors that need no cluster."""

import warnings

import pytest

from kfp import server_api as models
from kfp.client._native import NativeBackend


class _Transport:
    kubernetes_host = 'https://kubernetes.example'

    def __init__(self, archive_error):
        self.archive_error = archive_error

    def collection(
        self, path, *, params=None, kubernetes=False, metadata_only=False
    ):
        if path.startswith('/argo/api/v1/archived-workflows'):
            raise self.archive_error
        assert kubernetes
        return [{'metadata': {'uid': 'live-1', 'name': 'live'}}]


def test_run_inventory_falls_back_to_live_workflows_without_archive_access():
    """C18: a client without Argo archive access lists live runs and says once
    that archived ones are missing."""
    backend = NativeBackend.__new__(NativeBackend)
    backend.transport = _Transport(
        models.ApiException(status=404, reason='Not Found')
    )
    backend._archive_warned = False
    with pytest.warns(UserWarning, match='Archived runs are not listed'):
        resources = backend._workflow_resources('team', tolerate_archive=True)
    assert list(resources) == ['live-1']
    with warnings.catch_warnings():
        warnings.simplefilter('error')
        assert list(
            backend._workflow_resources('team', tolerate_archive=True)
        ) == ['live-1']
    # Mutations that must reach every run keep seeing the failure.
    with pytest.raises(models.ApiException):
        backend._workflow_resources('team')


class _InfoTransport:
    def __init__(self, info):
        self.info = info

    def request(self, method, path):
        assert (method, path) == ('GET', '/argo/api/v1/info')
        return self.info


@pytest.mark.parametrize(
    'info, multi_user',
    [
        ({'managedNamespace': 'kfp-argo'}, False),
        ({'modals': {}}, True),
        ({'kind': 'APIResourceList', 'resources': []}, False),
    ],
    ids=['namespaced-argo', 'cluster-wide-argo', 'kubernetes-discovery'],
)
def test_healthz_reports_the_deployment_scope(info, multi_user):
    """C40: multi-user is the cluster-wide Argo Server deployment; namespaced
    servers and the direct Kubernetes probe report a single namespace."""
    backend = NativeBackend.__new__(NativeBackend)
    backend.transport = _InfoTransport(info)
    response = backend.healthz_service_get_healthz()
    assert response.multi_user is multi_user
    assert response.pipeline_store == 'kubernetes'
