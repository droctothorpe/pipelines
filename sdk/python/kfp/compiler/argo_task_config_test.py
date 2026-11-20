# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0

import json

import pytest
import yaml

from kfp import compiler, dsl, kubernetes


def test_workspace_volume_passthrough_is_conditional_and_external_only(
    tmp_path,
):
    @dsl.component(
        task_config_passthroughs=[
            dsl.TaskConfigPassthrough(dsl.TaskConfigField.KUBERNETES_VOLUMES)
        ]
    )
    def external(workspace: str, config: dsl.TaskConfig):
        print(config.volumes)

    @dsl.pipeline(
        pipeline_config=dsl.PipelineConfig(
            workspace=dsl.WorkspaceConfig(
                size='1Gi',
                kubernetes=dsl.KubernetesWorkspaceConfig(
                    pvcSpecPatch={'accessModes': ['ReadWriteOnce']}
                ),
            )
        )
    )
    def pipeline():
        external(workspace=dsl.WORKSPACE_PATH_PLACEHOLDER)

    path = tmp_path / 'workspace-config.yaml'
    compiler.Compiler().compile(pipeline, str(path))
    template = next(
        t
        for t in yaml.safe_load(path.read_text())['spec']['templates']
        if 'container' in t
    )
    parameters = {p['name']: p for p in template['inputs']['parameters']}
    assert parameters['kfp-workspace-apply']['default'] == 'false'
    config = json.loads(parameters['config']['default'])
    assert config['__kfp_workspace__']['strings'] == ['workspace']
    assert 'workflow.name' not in parameters['config']['default'], (
        'Unused workspace context must not invalidate cross-run caching'
    )
    assert 'workflow.uid' in template['memoize']['key']


def test_volume_passthrough_keeps_task_local_scratch_volumes(tmp_path):
    @dsl.component(
        task_config_passthroughs=[
            dsl.TaskConfigPassthrough(dsl.TaskConfigField.KUBERNETES_VOLUMES)
        ]
    )
    def external(config: dsl.TaskConfig):
        print(config.volumes)

    @dsl.pipeline
    def pipeline():
        task = external()
        kubernetes.empty_dir_mount(task, 'scratch', '/scratch')
        kubernetes.use_config_map_as_volume(task, 'config', '/config')

    path = tmp_path / 'volumes.yaml'
    compiler.Compiler().compile(pipeline, str(path))
    template = next(
        t
        for t in yaml.safe_load(path.read_text())['spec']['templates']
        if 'container' in t
    )
    config = json.loads(
        next(
            p['default']
            for p in template['inputs']['parameters']
            if p['name'] == 'config'
        )
    )
    assert len(config['volumes']) == 1
    assert config['volumes'][0]['configMap']['name'] == 'config'
    assert template['volumes'] == [{'name': 'scratch', 'emptyDir': {}}]
    assert template['container']['volumeMounts'] == [
        {'name': 'scratch', 'mountPath': '/scratch'}
    ]


def test_dynamic_resource_claims_can_be_forwarded_without_pod_allocation(
    tmp_path,
):
    @dsl.component(
        task_config_passthroughs=[
            dsl.TaskConfigPassthrough(
                dsl.TaskConfigField.KUBERNETES_RESOURCE_CLAIMS
            )
        ]
    )
    def external(config: dsl.TaskConfig):
        print(config.resource_claims)

    @dsl.pipeline
    def pipeline(claims: list):
        kubernetes.add_resource_claim_json(external(), claims)

    path = tmp_path / 'dynamic-claims.yaml'
    compiler.Compiler().compile(pipeline, str(path))
    template = next(
        t
        for t in yaml.safe_load(path.read_text())['spec']['templates']
        if 'container' in t
    )
    config = json.loads(
        next(
            p['default']
            for p in template['inputs']['parameters']
            if p['name'] == 'config'
        )
    )
    assert '__kfp_native_claims__' in config['resourceClaims']
    assert 'resourceClaims' not in template
    assert not template['container'].get('resources', {}).get('claims')


def test_resource_claim_passthrough_does_not_allocate_on_the_task(tmp_path):
    @dsl.component(
        task_config_passthroughs=[
            dsl.TaskConfigPassthrough(
                dsl.TaskConfigField.KUBERNETES_RESOURCE_CLAIMS
            )
        ]
    )
    def external(config: dsl.TaskConfig):
        print(config.resource_claims)

    @dsl.pipeline
    def pipeline():
        kubernetes.add_resource_claim(external(), 'gpu-template')

    path = tmp_path / 'claims.yaml'
    compiler.Compiler().compile(pipeline, str(path))
    template = next(
        t
        for t in yaml.safe_load(path.read_text())['spec']['templates']
        if 'container' in t
    )
    config = json.loads(
        next(
            p['default']
            for p in template['inputs']['parameters']
            if p['name'] == 'config'
        )
    )
    assert config['resourceClaims'] == [
        {'name': 'gpu-template', 'resourceClaimTemplateName': 'gpu-template'}
    ]
    assert 'resourceClaims' not in template
    assert not template['container'].get('resources', {}).get('claims')


@pytest.mark.parametrize('apply', [False, True])
def test_task_config_projects_fields_and_honors_apply_to_task(tmp_path, apply):
    @dsl.component(
        task_config_passthroughs=[
            dsl.TaskConfigPassthrough(
                dsl.TaskConfigField.RESOURCES, apply_to_task=apply
            ),
            dsl.TaskConfigPassthrough(
                dsl.TaskConfigField.ENV, apply_to_task=apply
            ),
        ]
    )
    def external(config: dsl.TaskConfig) -> dict:
        return {'resources': config.resources, 'env': config.env}

    @dsl.pipeline
    def pipeline():
        external().set_cpu_limit('2').set_env_variable(
            'EXTERNAL_VALUE', 'configured'
        )

    path = tmp_path / 'task-config.yaml'
    compiler.Compiler().compile(pipeline, str(path))
    template = next(
        t
        for t in yaml.safe_load(path.read_text())['spec']['templates']
        if 'container' in t
    )
    parameter = next(
        (
            p
            for p in template.get('inputs', {}).get('parameters', [])
            if p['name'] == 'config'
        ),
        None,
    )
    assert parameter is not None, (
        'TaskConfig must be injected, not silently empty'
    )
    config = json.loads(parameter['default'])
    assert str(config['resources']['limits']['cpu']) == '2'
    assert config['env'] == [{'name': 'EXTERNAL_VALUE', 'value': 'configured'}]
    assert bool(template['container'].get('resources')) is apply
    assert (
        any(e['name'] == 'EXTERNAL_VALUE' for e in template['container']['env'])
        is apply
    )
    assert any(
        e['name'] == 'KFP_ARGO_RUN_UID' for e in template['container']['env']
    )
