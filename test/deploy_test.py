# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0

import importlib.util
from pathlib import Path

import pytest
import yaml

DEPLOY = Path(__file__).resolve().parents[1] / 'samples' / 'argo-native'

NAMESPACE_ENV = {
    'name': 'KFP_UI_NAMESPACE',
    'valueFrom': {'fieldRef': {'fieldPath': 'metadata.namespace'}},
}


def load_deployment():
    spec = importlib.util.spec_from_file_location(
        'deployment', DEPLOY / 'deploy.py'
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def proxy_bindings(result):
    return sorted(
        item['roleRef']['name']
        for item in result
        if item['kind'] == 'RoleBinding'
        and any(
            subject['name'] == 'argo-ui-proxy' for subject in item['subjects']
        )
    )


def ui_container(result):
    deployment = next(
        item
        for item in result
        if item['kind'] == 'Deployment'
        and item['metadata']['name'] == 'kfp-argo-ui'
    )
    return deployment['spec']['template']['spec']['containers'][0]


def test_isolated_client_auth_and_persistent_services():
    module = load_deployment()
    upstream = []
    for name in (
        'argo-server',
        'workflow-controller',
        'minio',
        'postgres',
        'httpbin',
    ):
        container = {
            'name': name,
            'image': 'quay.io/argoproj/example:latest',
            'lifecycle': {
                'postStart': {
                    'exec': {'command': ['mkdir', '-p', '/data/my-bucket']}
                }
            },
        }
        upstream.append(
            {
                'apiVersion': 'apps/v1',
                'kind': 'Deployment',
                'metadata': {'name': name, 'namespace': 'argo'},
                'spec': {'template': {'spec': {'containers': [container]}}},
            }
        )
    result = module.resources(upstream, 'isolated', 'ui:test')
    deployments = {
        item['metadata']['name']: item
        for item in result
        if item['kind'] == 'Deployment'
    }
    assert 'httpbin' not in deployments
    args = deployments['argo-server']['spec']['template']['spec']['containers'][
        0
    ]['args']
    assert args == [
        'server',
        '--auth-mode',
        'client',
        '--namespaced',
        '--managed-namespace',
        'isolated',
    ]
    assert (
        len(
            [item for item in result if item['kind'] == 'PersistentVolumeClaim']
        )
        == 2
    )
    for name in ('minio', 'postgres'):
        assert (
            deployments[name]['spec']['template']['spec']['volumes'][0][
                'persistentVolumeClaim'
            ]['claimName']
            == name + '-data'
        )
    proxy = deployments['kfp-argo-ui']['spec']['template']['spec']
    assert proxy['serviceAccountName'] == 'argo-ui-proxy'
    assert proxy_bindings(result) == []
    assert ui_container(result)['env'] == [
        {'name': 'KFP_UI_AUTH_MODE', 'value': 'token'},
        NAMESPACE_ENV,
    ]
    assert all(
        item['metadata'].get('namespace', 'isolated') == 'isolated'
        for item in result
    )


def test_single_user_mode_binds_proxy_and_publishes_mode():
    """Single-user mode is opt-in: the proxy gets namespace editor rights and the
    rendered nginx config advertises the mode and uses the pod's own token."""
    module = load_deployment()
    result = module.resources([], 'isolated', 'ui:test', 'single-user')
    assert proxy_bindings(result) == ['argo-ui-edit', 'argo-ui-read']
    assert all(
        item['metadata']['namespace'] == 'isolated'
        for item in result
        if item['kind'] == 'RoleBinding'
    )
    assert ui_container(result)['env'] == [
        {'name': 'KFP_UI_AUTH_MODE', 'value': 'single-user'},
        NAMESPACE_ENV,
    ]
    assert ui_container(result)['volumeMounts'][0]['mountPath'] == (
        '/etc/nginx/templates'
    )
    template = next(
        item
        for item in result
        if item['kind'] == 'ConfigMap'
        and item['metadata']['name'] == 'kfp-argo-ui-nginx'
    )['data']['default.conf.template']
    assert '${KFP_UI_AUTH_MODE}' in template
    assert '"namespace":"${KFP_UI_NAMESPACE}"' in template
    assert 'single-user $service_account_authorization;' in template
    assert 'default $http_authorization;' in template
    assert template.count('Authorization $upstream_authorization') == 2
    assert '$http_authorization;\n' not in template.split('map ')[0]
    with pytest.raises(ValueError):
        module.resources([], 'isolated', 'ui:test', 'anonymous')


def test_reader_cannot_mutate_and_no_cluster_admin_browser_binding():
    resources = list(
        yaml.safe_load_all((DEPLOY / 'native-rbac.yaml').read_text())
    )
    assert not any(item['kind'].startswith('ClusterRole') for item in resources)
    read = next(
        item
        for item in resources
        if item['kind'] == 'Role' and item['metadata']['name'] == 'argo-ui-read'
    )
    assert all(
        set(rule['verbs']) <= {'get', 'list', 'watch'} for rule in read['rules']
    )
    assert (
        'watch'
        in next(rule for rule in read['rules'] if 'pods' in rule['resources'])[
            'verbs'
        ]
    )
    edit = next(
        item
        for item in resources
        if item['kind'] == 'Role' and item['metadata']['name'] == 'argo-ui-edit'
    )
    metadata = next(
        rule for rule in edit['rules'] if rule['resources'] == ['configmaps']
    )
    assert 'update' in metadata['verbs'], (
        'SDK/UI archive state requires ConfigMap updates'
    )
    templates = next(
        rule
        for rule in edit['rules']
        if rule['resources'] == ['workflowtemplates']
    )
    assert (
        'update' not in templates['verbs'] and 'patch' not in templates['verbs']
    )


def test_template_offload_grants_controller_creation_only():
    resources = list(
        yaml.safe_load_all((DEPLOY / 'native-rbac.yaml').read_text())
    )
    role = next(
        (
            r
            for r in resources
            if r['kind'] == 'Role'
            and r['metadata']['name'] == 'kfp-template-config'
        ),
        None,
    )
    assert role is not None, (
        'Large native templates require controller ConfigMap creation'
    )
    assert role['rules'] == [
        {'apiGroups': [''], 'resources': ['configmaps'], 'verbs': ['create']}
    ]
    binding = next(
        r
        for r in resources
        if r['kind'] == 'RoleBinding'
        and r['metadata']['name'] == 'kfp-template-config'
    )
    assert binding['subjects'] == [{'kind': 'ServiceAccount', 'name': 'argo'}]
    workflow = next(
        r
        for r in resources
        if r['kind'] == 'Role' and r['metadata']['name'] == 'argo-workflow'
    )
    assert workflow['rules'] == [
        {
            'apiGroups': ['argoproj.io'],
            'resources': ['workflowtaskresults'],
            'verbs': ['create', 'patch'],
        }
    ]
