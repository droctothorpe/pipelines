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
