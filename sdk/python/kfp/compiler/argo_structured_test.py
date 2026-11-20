# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0

import json
from types import SimpleNamespace

import pytest

from kfp.compiler.argo_structured import MARKER, expression, finalize
from kfp.dsl.argo_runtime import resolve_task_config


def test_literal_delimiters_cannot_close_a_generated_expression():
    value = expression({'command': ['python3', '-c', 'print({"x": {"y": 1}})']})
    assert '}}' not in value
    assert r'\u007d' in value


def test_input_references_and_literal_segments_keep_string_types():
    assert (
        expression('prefix-{{inputs.parameters.value}}')
        == '"prefix-" + string(inputs.parameters["value"])'
    )
    assert (
        expression({MARKER: '{{inputs.parameters.selector}}'})
        == 'fromJSON(inputs.parameters["selector"])'
    )


def test_dynamic_argv_preserves_other_main_container_and_pod_settings():
    template = {
        'podSpecPatch': json.dumps(
            {
                'containers': [
                    {'name': 'main', 'securityContext': {'runAsUser': 1000}},
                    {'name': 'sidecar', 'image': 'busybox'},
                ],
                'initContainers': [
                    {'name': 'setup', 'command': ['echo', 'init']}
                ],
            }
        ),
        'nodeSelector': {MARKER: '{{inputs.parameters.selector}}'},
    }
    finalize(
        template,
        SimpleNamespace(inputs={}),
        container_expressions={
            'args': 'inputs.parameters.flag == "null" ? [] : ["--flag"]'
        },
    )
    source = template['podSpecPatch']
    assert source.startswith('{{=toJson(')
    for value in [
        '"securityContext"',
        '"runAsUser",1000',
        '"sidecar"',
        '"initContainers"',
        'fromJSON(inputs.parameters["selector"])',
        'inputs.parameters.flag == "null" ? []',
    ]:
        assert value in source


def test_task_config_resolves_only_controlled_json_markers():
    config = {
        'nodeSelector': {MARKER: 'selector'},
        'env': [{'name': 'TEXT', 'value': 'plain'}],
    }
    result = resolve_task_config(config, {'selector': '{"pool":"training"}'})
    assert result == {
        'nodeSelector': {'pool': 'training'},
        'env': [{'name': 'TEXT', 'value': 'plain'}],
    }
    with pytest.raises(ValueError, match='JSON object'):
        resolve_task_config(config, {'selector': '[]'})
    with pytest.raises(ValueError):
        resolve_task_config(config, {'selector': '{"number":NaN}'})


def _settings_pipeline(include_static, affinity_default={}):
    from kfp import dsl, kubernetes

    @dsl.component(base_image='python:3.11', install_kfp_package=False)
    def noop() -> str:
        return 'x'

    @dsl.pipeline(name='mixed-settings')
    def pipeline(
        claim: dict = {'resourceClaimTemplateName': 'dynamic-template'},
        affinity: dict = affinity_default,
    ):
        task = noop()
        kubernetes.add_resource_claim_json(task, claim)
        kubernetes.add_node_affinity_json(task, affinity)
        if include_static:
            kubernetes.add_resource_claim(task, 'static-template')
            kubernetes.add_node_affinity(
                task,
                match_expressions=[
                    {
                        'key': 'kubernetes.io/os',
                        'operator': 'In',
                        'values': ['linux'],
                    }
                ],
            )

    return pipeline


def _pod_spec_patch(pipeline, tmp_path):
    import yaml

    from kfp import compiler

    path = tmp_path / 'mixed.yaml'
    compiler.Compiler().compile(pipeline, str(path), resource_kind='Workflow')
    templates = yaml.safe_load(path.read_text())['spec']['templates']
    return next(t for t in templates if 'container' in t)['podSpecPatch']


def test_mixed_node_affinity_and_claims_merge_static_and_dynamic(tmp_path):
    """C10/C11: static terms and claims come first and the dynamic JSON value
    appends its own at run time; a null value contributes nothing."""
    patch = _pod_spec_patch(_settings_pipeline(True), tmp_path)
    assert (
        '"requiredDuringSchedulingIgnoredDuringExecution",len(concat([sprig.dict("matchExpressions",[sprig.dict("key","kubernetes.io/os","operator","In","values",["linux"])])], (fromJSON(inputs.parameters["kfp-config-1"])?.requiredDuringSchedulingIgnoredDuringExecution?.nodeSelectorTerms ?? []))) > 0 ? sprig.dict("nodeSelectorTerms", concat('
        in patch
    )
    assert (
        '"preferredDuringSchedulingIgnoredDuringExecution",concat([], (fromJSON(inputs.parameters["kfp-config-1"])?.preferredDuringSchedulingIgnoredDuringExecution ?? []))'
        in patch
    )
    assert (
        '"resourceClaims",concat([sprig.dict("resourceClaimTemplateName","static-template","name","static-template")], (fromJSON(inputs.parameters["kfp-config-0"]) == nil ? [] : map('
        in patch
    )
    assert (
        '"claims",concat([sprig.dict("name","static-template")], (fromJSON(inputs.parameters["kfp-config-0"]) == nil ? [] : map('
        in patch
    )


def test_single_dynamic_settings_keep_the_pass_through_form(tmp_path):
    patch = _pod_spec_patch(_settings_pipeline(False), tmp_path)
    assert '"nodeAffinity",fromJSON(inputs.parameters["kfp-config-1"])' in patch
    assert '"resourceClaims",map(' in patch
    assert 'concat(' not in patch


def test_null_dynamic_affinity_merges_with_static_terms(tmp_path):
    patch = _pod_spec_patch(
        _settings_pipeline(True, affinity_default=None), tmp_path
    )
    assert '?.nodeSelectorTerms ?? [])' in patch
