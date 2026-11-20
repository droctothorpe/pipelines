# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Authentication/TLS compatibility at the native HTTP boundary."""

import kfp
import kubernetes
import pytest
import requests
from kfp.client._transport import NativeTransport
from kfp.server_api import Configuration


def record_requests(monkeypatch):
    recorded = []

    def request(session, method, url, **kwargs):
        recorded.append({'method': method, 'url': url, **kwargs})
        response = requests.Response()
        response.status_code = 200
        response._content = b'{}'
        return response

    monkeypatch.setattr(requests.Session, 'request', request)
    return recorded


def test_kubeconfig_connection_uses_direct_resource_apis(monkeypatch):
    recorded = record_requests(monkeypatch)
    configuration = Configuration(
        host='https://kube.invalid/api/v1/namespaces/team/services/kfp-argo-ui:80/proxy/'
    )
    configuration._native_kubernetes_host = 'https://kube.invalid'
    transport = NativeTransport(configuration)
    transport.request('GET', '/kubernetes/api/v1/namespaces/team/configmaps')
    assert (
        recorded[-1]['url']
        == 'https://kube.invalid/api/v1/namespaces/team/configmaps'
    )
    workflow = {
        'apiVersion': 'argoproj.io/v1alpha1',
        'kind': 'Workflow',
        'metadata': {'generateName': 'test-', 'namespace': 'team'},
        'spec': {},
    }
    transport.request(
        'POST',
        '/argo/api/v1/workflows/team',
        body={'namespace': 'team', 'workflow': workflow},
    )
    assert (
        recorded[-1]['url']
        == 'https://kube.invalid/apis/argoproj.io/v1alpha1/namespaces/team/workflows'
    )
    assert recorded[-1]['json'] == workflow
    transport.request(
        'GET',
        '/argo/api/v1/cron-workflows/team',
        params={
            'listOptions.limit': 10,
            'listOptions.labelSelector': 'owned=true',
        },
    )
    assert recorded[-1]['params'] == {
        'limit': 10,
        'labelSelector': 'owned=true',
    }


@pytest.mark.parametrize('token', [None, 'explicit-service-account-token'])
def test_client_loads_kubeconfig_endpoint_and_respects_explicit_token(
    monkeypatch, tmp_path, token
):
    recorded = record_requests(monkeypatch)
    monkeypatch.setattr(
        kfp.Client, '_LOCAL_KFP_CONTEXT', str(tmp_path / 'context.json')
    )
    monkeypatch.delenv('KF_PIPELINES_ENDPOINT', raising=False)

    def outside_cluster(*args, **kwargs):
        raise kubernetes.config.ConfigException('outside cluster')

    def load(client_configuration, context):
        assert context == 'chosen'
        client_configuration.host = 'https://kube.invalid'
        client_configuration.cert_file = '/kube/client.crt'
        client_configuration.key_file = '/kube/client.key'
        client_configuration.ssl_ca_cert = '/kube/ca.crt'

    monkeypatch.setattr(
        kubernetes.config, 'load_incluster_config', outside_cluster
    )
    monkeypatch.setattr(kubernetes.config, 'load_kube_config', load)
    client = kfp.Client(
        kube_context='chosen', namespace='team', existing_token=token
    )
    client.list_experiments(namespace='team')
    request = recorded[-1]
    assert (
        request['url']
        == 'https://kube.invalid/api/v1/namespaces/team/configmaps'
    )
    assert request['verify'] == '/kube/ca.crt'
    if token:
        assert request['headers']['Authorization'] == 'Bearer ' + token
        assert request['cert'] is None, (
            'Explicit SA token must not inherit a more privileged certificate identity'
        )
    else:
        assert request['cert'] == ('/kube/client.crt', '/kube/client.key')


def test_incluster_service_account_refresh_is_preserved(monkeypatch, tmp_path):
    recorded = record_requests(monkeypatch)
    monkeypatch.setattr(
        kfp.Client, '_LOCAL_KFP_CONTEXT', str(tmp_path / 'context.json')
    )
    monkeypatch.delenv('KF_PIPELINES_ENDPOINT', raising=False)

    def load(client_configuration):
        client_configuration.host = 'https://kubernetes.default.svc'
        client_configuration.ssl_ca_cert = '/mounted/ca.crt'
        client_configuration.api_key['BearerToken'] = 'Bearer initial'

        def refresh(configuration):
            configuration.api_key['BearerToken'] = 'Bearer rotated'

        client_configuration.refresh_api_key_hook = refresh

    monkeypatch.setattr(kubernetes.config, 'load_incluster_config', load)
    client = kfp.Client(namespace='team')
    client.list_experiments(namespace='team')
    client.list_experiments(namespace='team')
    assert (
        recorded[-1]['url']
        == 'https://kubernetes.default.svc/api/v1/namespaces/team/configmaps'
    )
    assert recorded[-1]['headers']['Authorization'] == 'Bearer rotated'
    assert recorded[-1]['verify'] == '/mounted/ca.crt'


def test_direct_termination_keeps_uid_and_resource_version(monkeypatch):
    from kfp.client._native import NativeBackend

    recorded = record_requests(monkeypatch)
    configuration = Configuration(host='https://kube.invalid/proxy')
    configuration._native_kubernetes_host = 'https://kube.invalid'
    backend = NativeBackend(configuration, namespace=lambda: 'team')
    resource = {
        'metadata': {
            'name': 'run',
            'namespace': 'team',
            'uid': 'owned',
            'resourceVersion': '7',
        },
        'spec': {},
    }
    monkeypatch.setattr(backend, '_workflow', lambda identity: (resource, True))
    backend.run_service_terminate_run('owned')
    assert recorded[-1]['method'] == 'PUT'
    assert (
        recorded[-1]['url']
        == 'https://kube.invalid/apis/argoproj.io/v1alpha1/namespaces/team/workflows/run'
    )
    assert recorded[-1]['json']['metadata']['uid'] == 'owned'
    assert recorded[-1]['json']['metadata']['resourceVersion'] == '7'
    assert recorded[-1]['json']['spec']['shutdown'] == 'Terminate'


def test_verify_ssl_false_takes_precedence_over_ca_file(monkeypatch):
    recorded = record_requests(monkeypatch)
    configuration = Configuration(host='https://native.invalid')
    configuration.verify_ssl = False
    configuration.ssl_ca_cert = '/custom/ca.pem'
    configuration.cert_file = '/custom/client.pem'
    configuration.key_file = '/custom/client-key.pem'
    NativeTransport(configuration).request('GET', '/argo/api/v1/info')
    assert recorded[0]['verify'] is False
    assert recorded[0]['cert'] == (
        '/custom/client.pem',
        '/custom/client-key.pem',
    )


def test_basic_credentials_and_refreshed_bearer_precedence(monkeypatch):
    recorded = record_requests(monkeypatch)
    configuration = Configuration(
        host='https://native.invalid', username='user', password='test-password'
    )
    transport = NativeTransport(configuration)
    transport.request('GET', '/argo/api/v1/info')
    assert (
        recorded[-1]['headers']['Authorization']
        == configuration.get_basic_auth_token()
    )
    configuration.api_key_prefix['authorization'] = 'Bearer'
    configuration.refresh_api_key_hook = lambda config: config.api_key.update(
        authorization='refreshed-test-token'
    )
    transport.request('GET', '/argo/api/v1/info')
    assert (
        recorded[-1]['headers']['Authorization']
        == 'Bearer refreshed-test-token'
    )
