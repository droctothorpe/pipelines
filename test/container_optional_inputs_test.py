# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Raw optional arguments retain stock None/presence semantics."""

import json

import yaml
from e2e.pipelines.container_optional_inputs import pipeline
from kfp import compiler


def test_nullable_if_present_lowers_to_native_argument_arrays(tmp_path):
    path = tmp_path / 'pipeline.yaml'
    compiler.Compiler().compile(pipeline, str(path))
    manifest = yaml.safe_load(path.read_text())
    task = next(
        template
        for template in manifest['spec']['templates']
        if template.get('container', {}).get('image') == 'busybox:1.37'
    )
    assert json.loads(
        task['metadata']['annotations'][
            'pipelines.kubeflow.org/input-parameter-types'
        ]
    ) == {'value': 'NullableString'}
    assert task['podSpecPatch'].startswith('{{=toJson(')
    assert 'inputs.parameters["value"]' in task['podSpecPatch']
    assert 'initContainers' not in task
    assert task['container']['command'][0] == 'sh'
    assert task['memoize']['maxAge'] == ''
    root = manifest['spec']['templates'][0]
    argument = root['dag']['tasks'][0]['arguments']['parameters'][0]['value']
    assert 'Required parameter cannot be None' not in argument
    staged = next(
        template
        for template in manifest['spec']['templates']
        if template.get('initContainers')
    )
    argument_file = next(
        artifact
        for artifact in staged['inputs']['artifacts']
        if artifact['name'] == 'kfp-staging-args'
    )
    source = argument_file['raw']['data']
    assert 'kfp-meta-datasets' in source and " != 'null'" in source
    assert 'IfPresent' not in source
    assert any(
        env['name'] == 'ARGO_CONTAINER_ARGS_FILE'
        for env in staged['container']['env']
    )
    assert staged['container']['image'] == 'busybox:1.37'
