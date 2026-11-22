# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Emit the native deployment: Argo, persistent archive/artifacts and static UI.

Uses upstream quick-start development credentials. Bind port-forwards to loopback;
only multi-user mode behind an authenticating gateway is a multi-tenant installation.

UI authentication modes:
- token (default): the proxy forwards the browser's namespace-scoped bearer token
  and holds no Kubernetes privileges of its own.
- single-user: the proxy authenticates with its own editor-bound service account,
  so the UI needs no login. Only for disposable local single-user namespaces.
- multi-user: Argo runs cluster-wide, the proxy trusts the identity header set by
  the authenticating gateway (Kubeflow's Istio ingress with oauth2-proxy), checks
  every request for that user with a SubjectAccessReview and acts with its own
  cluster-scoped account. Tenant namespaces are prepared with --tenant.
"""

import argparse
import copy
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
VERSION = (ROOT / 'third_party/argo/VERSION').read_text().strip()


AUTH_MODES = ('token', 'single-user', 'multi-user')
DEFAULT_USERID_HEADER = 'kubeflow-userid'
DEFAULT_INGRESS_PRINCIPAL = (
    'cluster.local/ns/istio-system/sa/istio-ingressgateway-service-account'
)
# Per-namespace resources every namespace that runs pipelines needs.
TENANT_RESOURCES = {'argo-workflow', 'kfp-cache', 'kfp-template-config'}
# The Kubeflow profile controller binds these aggregated roles to namespace members.
AGGREGATION = 'rbac.authorization.kubeflow.org/aggregate-to-kubeflow-'


def native_rbac():
    return [
        resource
        for resource in yaml.safe_load_all(
            Path(__file__).with_name('native-rbac.yaml').read_text()
        )
        if resource
    ]


def role_rules(name):
    return next(
        item['rules']
        for item in native_rbac()
        if item['kind'] == 'Role' and item['metadata']['name'] == name
    )


def cluster_role(name, rules, labels=None):
    metadata = {'name': name}
    if labels:
        metadata['labels'] = labels
    return {
        'apiVersion': 'rbac.authorization.k8s.io/v1',
        'kind': 'ClusterRole',
        'metadata': metadata,
        'rules': rules,
    }


def multi_user_rbac(namespace):
    """Cluster-wide proxy rights gated by per-user SubjectAccessReviews, and
    the aggregated roles that give Kubeflow namespace members pipeline
    access."""
    read = role_rules('argo-ui-read')
    edit = role_rules('argo-ui-edit')
    return [
        cluster_role(
            'argo-ui-proxy',
            read
            + edit
            + [
                {
                    'apiGroups': ['authorization.k8s.io'],
                    'resources': ['subjectaccessreviews'],
                    'verbs': ['create'],
                }
            ],
        ),
        {
            'apiVersion': 'rbac.authorization.k8s.io/v1',
            'kind': 'ClusterRoleBinding',
            'metadata': {'name': 'argo-ui-proxy'},
            'roleRef': {
                'apiGroup': 'rbac.authorization.k8s.io',
                'kind': 'ClusterRole',
                'name': 'argo-ui-proxy',
            },
            'subjects': [
                {
                    'kind': 'ServiceAccount',
                    'name': 'argo-ui-proxy',
                    'namespace': namespace,
                }
            ],
        },
        cluster_role('kfp-native-view', read, {AGGREGATION + 'view': 'true'}),
        cluster_role(
            'kfp-native-edit', read + edit, {AGGREGATION + 'edit': 'true'}
        ),
    ]


def gateway_resources(namespace, gateway, ingress_principal):
    """Serve the UI at /pipeline through a Kubeflow Istio gateway and accept
    traffic only from it, so the identity header is always the gateway's."""
    return [
        {
            'apiVersion': 'networking.istio.io/v1',
            'kind': 'VirtualService',
            'metadata': {'name': 'kfp-argo-ui', 'namespace': namespace},
            'spec': {
                'gateways': [gateway],
                'hosts': ['*'],
                'http': [
                    {
                        'match': [{'uri': {'prefix': '/pipeline'}}],
                        'route': [
                            {
                                'destination': {
                                    'host': f'kfp-argo-ui.{namespace}.svc.cluster.local',
                                    'port': {'number': 80},
                                }
                            }
                        ],
                        'timeout': '300s',
                    }
                ],
            },
        },
        {
            'apiVersion': 'security.istio.io/v1',
            'kind': 'AuthorizationPolicy',
            'metadata': {'name': 'kfp-argo-ui', 'namespace': namespace},
            'spec': {
                'selector': {'matchLabels': {'app': 'kfp-argo-ui'}},
                'rules': [
                    {'from': [{'source': {'principals': [ingress_principal]}}]}
                ],
            },
        },
    ]


def repository_data(configmap, namespace, multi_user):
    """Point the quick-start artifact repositories at the bundled bucket and,
    when other namespaces use them, at the object store's cross-namespace
    name."""
    for key, value in configmap.get('data', {}).items():
        value = value.replace('bucket: my-bucket', 'bucket: argo-artifacts')
        if multi_user:
            value = value.replace(
                'endpoint: minio:9000', f'endpoint: minio.{namespace}:9000'
            )
        configmap['data'][key] = value


def tenant_resources(upstream, namespace, tenant):
    """What a namespace needs to run pipelines under a cluster-wide controller:
    the workflow account, cache state, template offload rights, and the artifact
    repository with its credentials (the controller's own default is the
    quick-start's test plugin). Access for people comes from the aggregated
    Kubeflow roles."""
    result = []
    for original in upstream:
        if original and (original['kind'], original['metadata']['name']) in {
            ('Secret', 'my-minio-cred'),
            ('ConfigMap', 'artifact-repositories'),
        }:
            resource = copy.deepcopy(original)
            resource['metadata']['namespace'] = tenant
            if resource['kind'] == 'ConfigMap':
                repository_data(resource, namespace, True)
            result.append(resource)
    for resource in native_rbac():
        if resource['metadata']['name'] not in TENANT_RESOURCES:
            continue
        resource = copy.deepcopy(resource)
        resource['metadata']['namespace'] = tenant
        for subject in resource.get('subjects', []):
            # The controller's account lives in the platform namespace.
            if subject['name'] == 'argo':
                subject['namespace'] = namespace
        result.append(resource)
    return result


def resources(
    upstream,
    namespace,
    ui_image,
    auth_mode='token',
    userid_header=DEFAULT_USERID_HEADER,
    userid_prefix='',
    gateway=None,
    ingress_principal=DEFAULT_INGRESS_PRINCIPAL,
):
    if auth_mode not in AUTH_MODES:
        raise ValueError(
            f'auth_mode must be one of {AUTH_MODES}, not {auth_mode!r}'
        )
    multi_user = auth_mode == 'multi-user'
    if gateway and not multi_user:
        raise ValueError(
            'An Istio gateway is only meaningful in multi-user mode.'
        )
    result = [
        {
            'apiVersion': 'v1',
            'kind': 'Namespace',
            'metadata': {'name': namespace},
        }
    ]
    for original in upstream:
        if not original:
            continue
        resource = copy.deepcopy(original)
        metadata = resource.get('metadata', {})
        if metadata.get('name') in {
            'httpbin',
            'my-httpbin-cred',
            'github.com',
            'github.com.service-account-token',
            'default.service-account-token',
            'argo-server-sso',
            'argo-workflows-webhook-clients',
            'agent-default',
            'artifactgc-default',
            'executor-default',
            'pod-manager-default',
            'workflow-manager-default',
        }:
            continue
        if resource['kind'] == 'Namespace':
            continue
        if metadata.get('namespace') == 'argo':
            metadata['namespace'] = namespace
        for subject in resource.get('subjects', []):
            if subject.get('namespace') == 'argo':
                subject['namespace'] = namespace
        if resource['kind'] == 'ConfigMap':
            repository_data(resource, namespace, multi_user)
            if metadata['name'] == 'workflow-controller-configmap':
                resource['data']['executor'] = yaml.safe_dump(
                    {'image': f'quay.io/argoproj/argoexec:{VERSION}'}
                )
                # Retention is explicit in the test, not racing automatic deletion.
                resource['data'].pop('retentionPolicy', None)
        if resource['kind'] == 'Deployment':
            pod = resource['spec']['template']['spec']
            scope = (
                []
                if multi_user
                else ['--namespaced', '--managed-namespace', namespace]
            )
            for container in pod['containers']:
                if container['image'].startswith('quay.io/argoproj/'):
                    container['image'] = container['image'].replace(
                        ':latest', ':' + VERSION
                    )
                if metadata['name'] == 'argo-server':
                    container['args'] = [
                        'server',
                        '--auth-mode',
                        'client',
                    ] + scope
                elif metadata['name'] == 'workflow-controller':
                    container['args'] = scope
                    container.setdefault('env', []).append(
                        {'name': 'ALWAYS_OFFLOAD_NODE_STATUS', 'value': 'true'}
                    )
                elif metadata['name'] in ('minio', 'postgres'):
                    mount = (
                        '/data'
                        if metadata['name'] == 'minio'
                        else '/var/lib/pgsql/data'
                    )
                    container.setdefault('volumeMounts', []).append(
                        {'name': 'data', 'mountPath': mount}
                    )
                    pod['volumes'] = [
                        {
                            'name': 'data',
                            'persistentVolumeClaim': {
                                'claimName': metadata['name'] + '-data'
                            },
                        }
                    ]
                    resource['spec']['strategy'] = {'type': 'Recreate'}
                    if metadata['name'] == 'minio':
                        container['lifecycle']['postStart']['exec']['command'][
                            -1
                        ] = '/data/argo-artifacts'
                    else:
                        pod['securityContext'] = {'fsGroup': 26}
        result.append(resource)
    for name in ('minio-data', 'postgres-data'):
        result.append(
            {
                'apiVersion': 'v1',
                'kind': 'PersistentVolumeClaim',
                'metadata': {'name': name, 'namespace': namespace},
                'spec': {
                    'accessModes': ['ReadWriteOnce'],
                    'resources': {'requests': {'storage': '2Gi'}},
                },
            }
        )
    for resource in native_rbac():
        resource['metadata']['namespace'] = namespace
        result.append(resource)
    if auth_mode == 'single-user':
        for role in ('argo-ui-read', 'argo-ui-edit'):
            result.append(
                {
                    'apiVersion': 'rbac.authorization.k8s.io/v1',
                    'kind': 'RoleBinding',
                    'metadata': {
                        'name': f'argo-ui-proxy-{role.removeprefix("argo-ui-")}',
                        'namespace': namespace,
                    },
                    'roleRef': {
                        'apiGroup': 'rbac.authorization.k8s.io',
                        'kind': 'Role',
                        'name': role,
                    },
                    'subjects': [
                        {'kind': 'ServiceAccount', 'name': 'argo-ui-proxy'}
                    ],
                }
            )
    if multi_user:
        result.extend(multi_user_rbac(namespace))
        if gateway:
            result.extend(
                gateway_resources(namespace, gateway, ingress_principal)
            )
    nginx = Path(__file__).with_name('nginx.conf.template').read_text()
    result.append(
        {
            'apiVersion': 'v1',
            'kind': 'ConfigMap',
            'metadata': {'name': 'kfp-argo-ui-nginx', 'namespace': namespace},
            'data': {'default.conf.template': nginx},
        }
    )
    env = [{'name': 'KFP_UI_AUTH_MODE', 'value': auth_mode}]
    if multi_user:
        # The dashboard names the namespace; the platform namespace is no default.
        env += [
            {'name': 'KFP_UI_NAMESPACE', 'value': ''},
            {'name': 'KFP_UI_USERID_HEADER', 'value': userid_header},
            {'name': 'KFP_UI_USERID_PREFIX', 'value': userid_prefix},
        ]
    else:
        env.append(
            {
                'name': 'KFP_UI_NAMESPACE',
                'valueFrom': {'fieldRef': {'fieldPath': 'metadata.namespace'}},
            }
        )
    result.append(
        {
            'apiVersion': 'apps/v1',
            'kind': 'Deployment',
            'metadata': {'name': 'kfp-argo-ui', 'namespace': namespace},
            'spec': {
                'selector': {'matchLabels': {'app': 'kfp-argo-ui'}},
                'template': {
                    'metadata': {'labels': {'app': 'kfp-argo-ui'}},
                    'spec': {
                        'serviceAccountName': 'argo-ui-proxy',
                        'containers': [
                            {
                                'name': 'ui',
                                'image': ui_image,
                                'imagePullPolicy': 'IfNotPresent',
                                'ports': [{'containerPort': 8080}],
                                'env': env,
                                'readinessProbe': {
                                    'httpGet': {
                                        'path': '/argo.html',
                                        'port': 8080,
                                    }
                                },
                                'volumeMounts': [
                                    {
                                        'name': 'nginx',
                                        'mountPath': '/etc/nginx/templates',
                                        'readOnly': True,
                                    }
                                ],
                            }
                        ],
                        'volumes': [
                            {
                                'name': 'nginx',
                                'configMap': {'name': 'kfp-argo-ui-nginx'},
                            }
                        ],
                    },
                },
            },
        }
    )
    result.append(
        {
            'apiVersion': 'v1',
            'kind': 'Service',
            'metadata': {'name': 'kfp-argo-ui', 'namespace': namespace},
            'spec': {
                'selector': {'app': 'kfp-argo-ui'},
                'ports': [{'port': 80, 'targetPort': 8080}],
            },
        }
    )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--namespace', default='kfp-argo')
    parser.add_argument('--ui-image', default='kfp-argo-ui:dev')
    parser.add_argument(
        '--auth-mode',
        choices=AUTH_MODES,
        default='token',
        help='single-user lets the UI proxy authenticate with its own '
        'service account so no browser token is needed (local use only); '
        'multi-user trusts the gateway identity header and authorizes per user',
    )
    parser.add_argument(
        '--userid-header',
        default=DEFAULT_USERID_HEADER,
        help='multi-user: header the authenticating gateway sets to the user',
    )
    parser.add_argument(
        '--userid-prefix',
        default='',
        help='multi-user: prefix stripped from the header value, as stock does',
    )
    parser.add_argument(
        '--istio-gateway',
        help='multi-user: emit a VirtualService at /pipeline on this '
        'namespace/name gateway and admit only the ingress principal',
    )
    parser.add_argument(
        '--ingress-principal',
        default=DEFAULT_INGRESS_PRINCIPAL,
        help='Istio principal of the ingress gateway that sets the header',
    )
    parser.add_argument(
        '--tenant',
        help='emit only what this existing namespace needs to run pipelines '
        'under the multi-user deployment in --namespace',
    )
    args = parser.parse_args()
    url = f'https://raw.githubusercontent.com/argoproj/argo-workflows/{VERSION}/manifests/quick-start-postgres.yaml'
    with urllib.request.urlopen(url, timeout=60) as response:
        upstream = list(yaml.safe_load_all(response.read()))
    if args.tenant:
        emitted = tenant_resources(upstream, args.namespace, args.tenant)
    else:
        emitted = resources(
            upstream,
            args.namespace,
            args.ui_image,
            args.auth_mode,
            args.userid_header,
            args.userid_prefix,
            args.istio_gateway,
            args.ingress_principal,
        )
    print(yaml.safe_dump_all(emitted, sort_keys=False))


if __name__ == '__main__':
    main()
