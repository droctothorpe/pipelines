# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Validate Kubernetes modifiers at the native template boundary, not retired IR snapshots."""

import copy
import json

import pytest
import yaml

from kfp import compiler, dsl, kubernetes


@pytest.mark.parametrize(
    'method,kwargs,field,expected',
    [
        (
            'add_node_selector',
            {'label_key': 'pool', 'label_value': 'training'},
            'nodeSelector',
            {'pool': 'training'},
        ),
        (
            'add_pod_label',
            {'label_key': 'team', 'label_value': 'ml'},
            'metadata',
            {'labels': {'team': 'ml'}},
        ),
        (
            'add_pod_annotation',
            {'annotation_key': 'note', 'annotation_value': 'native'},
            'metadata',
            {'annotations': {'note': 'native'}},
        ),
        (
            'add_toleration',
            {'key': 'pool', 'operator': 'Exists'},
            'tolerations',
            [{'key': 'pool', 'operator': 'Exists'}],
        ),
        ('set_timeout', {'seconds': 60}, 'activeDeadlineSeconds', 60),
    ],
)
def test_template_fields(tmp_path, method, kwargs, field, expected):
    @dsl.container_component
    def step():
        return dsl.ContainerSpec(image='busybox', command=['true'])

    @dsl.pipeline
    def pipeline():
        getattr(kubernetes, method)(step(), **kwargs)

    path = tmp_path / 'pipeline.yaml'
    compiler.Compiler(disable_caching=True).compile(pipeline, str(path))
    template = next(
        t
        for t in yaml.safe_load(path.read_text())['spec']['templates']
        if 'container' in t
    )
    actual = copy.deepcopy(template[field])
    if field == 'metadata':
        policy = actual['annotations'].pop(
            'pipelines.kubeflow.org/cache-policy'
        )
        assert json.loads(policy)['component'] == 'step'
        assert (
            actual['annotations'].pop('pipelines.kubeflow.org/component-type')
            == 'RUNTIME'
        )
        for direction in ('input', 'output'):
            assert (
                json.loads(
                    actual['annotations'].pop(
                        'pipelines.kubeflow.org/'
                        + direction
                        + '-parameter-types'
                    )
                )
                == {}
            )
        if not actual['annotations']:
            del actual['annotations']
    assert actual == expected


def test_image_env_and_volume_bindings(tmp_path):
    @dsl.container_component
    def step():
        return dsl.ContainerSpec(image='busybox', command=['true'])

    @dsl.pipeline
    def pipeline():
        task = step()
        kubernetes.set_image_pull_policy(task, 'IfNotPresent')
        kubernetes.use_secret_as_env(task, 'secret', {'key': 'SECRET_VALUE'})
        kubernetes.use_config_map_as_env(
            task, 'config', {'key': 'CONFIG_VALUE'}
        )
        kubernetes.mount_pvc(task, 'data', '/data')

    path = tmp_path / 'pipeline.yaml'
    compiler.Compiler(disable_caching=True).compile(pipeline, str(path))
    template = next(
        t
        for t in yaml.safe_load(path.read_text())['spec']['templates']
        if 'container' in t
    )
    assert template['container']['imagePullPolicy'] == 'IfNotPresent'
    env = {
        entry['name']: entry['valueFrom']
        for entry in template['container']['env']
    }
    assert env['SECRET_VALUE']['secretKeyRef'] == {
        'name': 'secret',
        'key': 'key',
        'optional': False,
    }
    assert env['CONFIG_VALUE']['configMapKeyRef'] == {
        'name': 'config',
        'key': 'key',
        'optional': False,
    }
    assert (
        template['volumes'][0]['persistentVolumeClaim']['claimName'] == 'data'
    )
    assert template['container']['volumeMounts'][0]['mountPath'] == '/data'


def test_volume_init_security_and_downward_api_settings(tmp_path):
    @dsl.container_component
    def step():
        return dsl.ContainerSpec(image='python:3.11', command=['true'])

    @dsl.pipeline
    def pipeline():
        task = step()
        kubernetes.set_image_pull_secrets(task, ['pull-secret'])
        kubernetes.use_config_map_as_volume(task, 'config', '/config')
        kubernetes.use_secret_as_volume(
            task, 'secret', '/secret', optional=True
        )
        kubernetes.empty_dir_mount(
            task, 'scratch', '/scratch', size_limit='1Mi'
        )
        kubernetes.use_field_path_as_env(task, 'NODE_NAME', 'spec.nodeName')
        kubernetes.add_init_container(
            task,
            'prepare',
            'python:3.11',
            command=['true'],
            volume_mounts={'scratch': '/scratch'},
            resource_requests={'cpu': '10m'},
        )
        kubernetes.set_security_context(
            task, run_as_user=1000, run_as_group=1000, run_as_non_root=True
        )
        kubernetes.add_node_affinity(
            task,
            match_expressions=[
                {'key': 'pool', 'operator': 'In', 'values': ['compute']}
            ],
            weight=10,
        )
        kubernetes.add_ephemeral_volume(
            task, 'ephemeral', '/ephemeral', ['ReadWriteOnce'], '1Mi'
        )

    path = tmp_path / 'settings.yaml'
    compiler.Compiler().compile(pipeline, str(path))
    template = next(
        t
        for t in yaml.safe_load(path.read_text())['spec']['templates']
        if 'container' in t
    )
    assert json.loads(template['podSpecPatch'])['imagePullSecrets'] == [
        {'name': 'pull-secret'}
    ]
    assert 'imagePullSecrets' not in template, (
        'This is a Pod field, not an Argo Template field'
    )
    assert any(
        v.get('secret', {}).get('secretName') == 'secret'
        and v['secret']['optional']
        for v in template['volumes']
    )
    assert any(
        v.get('configMap', {}).get('name') == 'config'
        for v in template['volumes']
    )
    assert all(v['name'] == v['name'].lower() for v in template['volumes'])
    assert (
        next(v for v in template['volumes'] if v['name'] == 'scratch')[
            'emptyDir'
        ]['sizeLimit']
        == '1Mi'
    )
    ephemeral = next(
        v for v in template['volumes'] if v['name'] == 'ephemeral'
    )['ephemeral']['volumeClaimTemplate']['spec']
    assert 'storageClassName' not in ephemeral
    assert template['initContainers'][0]['volumeMounts'] == [
        {'name': 'scratch', 'mountPath': '/scratch'}
    ]
    assert (
        template['initContainers'][0]['resources']['requests']['cpu'] == '10m'
    )
    assert template['container']['securityContext'] == {
        'runAsUser': 1000,
        'runAsGroup': 1000,
        'runAsNonRoot': True,
        'allowPrivilegeEscalation': False,
        'capabilities': {'drop': ['ALL']},
        'seccompProfile': {'type': 'RuntimeDefault'},
    }
    assert (
        template['affinity']['nodeAffinity'][
            'preferredDuringSchedulingIgnoredDuringExecution'
        ][0]['weight']
        == 10
    )
    env = next(
        e for e in template['container']['env'] if e['name'] == 'NODE_NAME'
    )
    assert env['valueFrom']['fieldRef']['fieldPath'] == 'spec.nodeName'


def test_dynamic_structured_settings_compose_with_resource_and_pull_secret_patches(
    tmp_path,
):
    @dsl.container_component
    def step():
        return dsl.ContainerSpec(image='python:3.11', command=['true'])

    @dsl.pipeline
    def pipeline(selector: dict, toleration: dict, cpu: str = '100m'):
        task = step().set_cpu_limit(cpu)
        kubernetes.add_node_selector_json(task, selector)
        kubernetes.add_toleration_json(task, toleration)
        kubernetes.set_image_pull_secrets(task, ['pull-secret'])

    path = tmp_path / 'dynamic.yaml'
    compiler.Compiler().compile(pipeline, str(path))
    template = next(
        t
        for t in yaml.safe_load(path.read_text())['spec']['templates']
        if 'container' in t
    )
    patch = template['podSpecPatch']
    assert patch.startswith('{{=toJson(')
    assert 'fromJSON' in patch
    assert 'imagePullSecrets' in patch
    assert 'resources' in patch
    assert 'nodeSelector' not in template
    assert 'tolerations' not in template
    assert '__kfp_native_json__' not in path.read_text()


def test_unmapped_configuration_is_rejected(tmp_path):
    @dsl.container_component
    def step():
        return dsl.ContainerSpec(image='busybox', command=['true'])

    @dsl.pipeline
    def pipeline():
        step().platform_config['kubernetes'] = {'unsupportedSetting': True}

    with pytest.raises(ValueError, match='no native lowering'):
        compiler.Compiler(disable_caching=True).compile(
            pipeline, str(tmp_path / 'pipeline.yaml')
        )
