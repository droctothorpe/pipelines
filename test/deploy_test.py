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
    assert 'token $http_authorization;' in template
    assert 'default $service_account_authorization;' in template
    assert template.count('auth_request /_kfp/authorize;') == 2
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


def multi_user(**kwargs):
    module = load_deployment()
    upstream = []
    for name in ('argo-server', 'workflow-controller'):
        upstream.append(
            {
                'apiVersion': 'apps/v1',
                'kind': 'Deployment',
                'metadata': {'name': name, 'namespace': 'argo'},
                'spec': {
                    'template': {
                        'spec': {
                            'containers': [
                                {
                                    'name': name,
                                    'image': 'quay.io/argoproj/example:latest',
                                }
                            ]
                        }
                    }
                },
            }
        )
    upstream.append(
        {
            'apiVersion': 'v1',
            'kind': 'ConfigMap',
            'metadata': {
                'name': 'workflow-controller-configmap',
                'namespace': 'argo',
            },
            'data': {
                'artifactRepository': 's3:\n  endpoint: minio:9000\n  bucket: my-bucket\n'
            },
        }
    )
    upstream.append(
        {
            'apiVersion': 'v1',
            'kind': 'Secret',
            'metadata': {'name': 'my-minio-cred', 'namespace': 'argo'},
            'stringData': {'accesskey': 'admin', 'secretkey': 'password'},
        }
    )
    upstream.append(
        {
            'apiVersion': 'v1',
            'kind': 'ConfigMap',
            'metadata': {
                'name': 'artifact-repositories',
                'namespace': 'argo',
                'annotations': {
                    'workflows.argoproj.io/default-artifact-repository': 'default-v1'
                },
            },
            'data': {
                'default-v1': 's3:\n  endpoint: minio:9000\n  bucket: my-bucket\n'
            },
        }
    )
    return (
        module,
        upstream,
        module.resources(
            upstream, 'platform', 'ui:test', 'multi-user', **kwargs
        ),
    )


def test_multi_user_mode_runs_cluster_wide_and_authorizes_per_user():
    """The stock multi-user model: Argo manages every namespace, the proxy acts
    with a cluster-scoped account after a SubjectAccessReview for the user the
    gateway names, and Kubeflow namespace members get rights by aggregation."""
    module, _, result = multi_user()
    by_kind = {}
    for item in result:
        by_kind.setdefault(item['kind'], {})[item['metadata']['name']] = item
    for name in ('argo-server', 'workflow-controller'):
        args = by_kind['Deployment'][name]['spec']['template']['spec'][
            'containers'
        ][0]['args']
        assert '--namespaced' not in args and '--managed-namespace' not in args
    assert by_kind['Deployment']['argo-server']['spec']['template']['spec'][
        'containers'
    ][0]['args'] == ['server', '--auth-mode', 'client']
    repository = by_kind['ConfigMap']['workflow-controller-configmap']['data'][
        'artifactRepository'
    ]
    assert 'endpoint: minio.platform:9000' in repository
    assert 'bucket: argo-artifacts' in repository
    proxy = by_kind['ClusterRole']['argo-ui-proxy']
    assert {
        'apiGroups': ['authorization.k8s.io'],
        'resources': ['subjectaccessreviews'],
        'verbs': ['create'],
    } in proxy['rules']
    assert module.role_rules('argo-ui-edit')[0] in proxy['rules']
    binding = by_kind['ClusterRoleBinding']['argo-ui-proxy']
    assert binding['subjects'] == [
        {
            'kind': 'ServiceAccount',
            'name': 'argo-ui-proxy',
            'namespace': 'platform',
        }
    ]
    assert proxy_bindings(result) == []
    view = by_kind['ClusterRole']['kfp-native-view']
    edit = by_kind['ClusterRole']['kfp-native-edit']
    assert view['metadata']['labels'] == {
        'rbac.authorization.kubeflow.org/aggregate-to-kubeflow-view': 'true'
    }
    assert edit['metadata']['labels'] == {
        'rbac.authorization.kubeflow.org/aggregate-to-kubeflow-edit': 'true'
    }
    assert view['rules'] == module.role_rules('argo-ui-read')
    assert edit['rules'] == module.role_rules(
        'argo-ui-read'
    ) + module.role_rules('argo-ui-edit')
    assert all(
        set(rule['verbs']) <= {'get', 'list', 'watch'} for rule in view['rules']
    )
    assert ui_container(result)['env'] == [
        {'name': 'KFP_UI_AUTH_MODE', 'value': 'multi-user'},
        {'name': 'KFP_UI_NAMESPACE', 'value': ''},
        {'name': 'KFP_UI_USERID_HEADER', 'value': 'kubeflow-userid'},
        {'name': 'KFP_UI_USERID_PREFIX', 'value': ''},
    ]
    assert 'VirtualService' not in by_kind
    env = ui_container(
        module.resources(
            [],
            'platform',
            'ui:test',
            'multi-user',
            userid_header='x-goog-authenticated-user-email',
            userid_prefix='accounts.google.com:',
        )
    )['env']
    assert {
        'name': 'KFP_UI_USERID_PREFIX',
        'value': 'accounts.google.com:',
    } in env


def test_multi_user_gateway_serves_pipeline_prefix_from_the_ingress_only():
    module, _, result = multi_user(gateway='kubeflow/kubeflow-gateway')
    virtual_service = next(
        item for item in result if item['kind'] == 'VirtualService'
    )
    assert virtual_service['metadata']['namespace'] == 'platform'
    route = virtual_service['spec']['http'][0]
    assert virtual_service['spec']['gateways'] == ['kubeflow/kubeflow-gateway']
    assert route['match'] == [{'uri': {'prefix': '/pipeline'}}]
    assert route['route'][0]['destination'] == {
        'host': 'kfp-argo-ui.platform.svc.cluster.local',
        'port': {'number': 80},
    }
    policy = next(
        item for item in result if item['kind'] == 'AuthorizationPolicy'
    )
    assert policy['spec']['selector'] == {'matchLabels': {'app': 'kfp-argo-ui'}}
    assert policy['spec']['rules'] == [
        {
            'from': [
                {
                    'source': {
                        'principals': [
                            'cluster.local/ns/istio-system/sa/istio-ingressgateway-service-account'
                        ]
                    }
                }
            ]
        }
    ]
    with pytest.raises(ValueError):
        module.resources(
            [],
            'platform',
            'ui:test',
            'token',
            gateway='kubeflow/kubeflow-gateway',
        )


def test_tenant_bundle_prepares_a_namespace_for_the_cluster_wide_controller():
    module, upstream, _ = multi_user()
    result = module.tenant_resources(upstream, 'platform', 'team-a')
    assert all(item['metadata']['namespace'] == 'team-a' for item in result)
    names = sorted((item['kind'], item['metadata']['name']) for item in result)
    assert names == [
        ('ConfigMap', 'artifact-repositories'),
        ('ConfigMap', 'kfp-cache'),
        ('Role', 'argo-workflow'),
        ('Role', 'kfp-cache'),
        ('Role', 'kfp-template-config'),
        ('RoleBinding', 'argo-workflow'),
        ('RoleBinding', 'kfp-cache'),
        ('RoleBinding', 'kfp-template-config'),
        ('Secret', 'my-minio-cred'),
        ('ServiceAccount', 'argo-workflow'),
    ]
    offload = next(
        item
        for item in result
        if item['kind'] == 'RoleBinding'
        and item['metadata']['name'] == 'kfp-template-config'
    )
    assert offload['subjects'] == [
        {'kind': 'ServiceAccount', 'name': 'argo', 'namespace': 'platform'}
    ]
    assert not any('argo-ui' in item['metadata']['name'] for item in result)
    repositories = next(
        item
        for item in result
        if item['metadata']['name'] == 'artifact-repositories'
    )
    assert repositories['metadata']['annotations'] == {
        'workflows.argoproj.io/default-artifact-repository': 'default-v1'
    }
    assert 'endpoint: minio.platform:9000' in repositories['data']['default-v1']
    assert 'bucket: argo-artifacts' in repositories['data']['default-v1']
