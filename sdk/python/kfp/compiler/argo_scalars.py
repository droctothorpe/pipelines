# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Validate raw-container scalar outputs using native DAG expressions, not
pods."""

import copy
import json


def expression(reference, kind):
    trimmed = f'sprig.trim({reference})'
    if kind == 'Integer':
        return f'toJson(asInt({trimmed}))'
    if kind == 'Float':
        return f'toJson(asFloat({trimmed}))'
    error = f'asInt({json.dumps("Invalid container output: expected " + kind)})'
    if kind == 'Boolean':
        return (
            f'{trimmed} in ["1", "t", "T", "TRUE", "true", "True"] ? "true" : '
            f'({trimmed} in ["0", "f", "F", "FALSE", "false", "False"] ? "false" : {error})'
        )
    expected = {'List': 'slice', 'Dict': 'map'}[kind]
    parsed = f'fromJSON({reference})'
    return (
        f'sprig.kindOf({parsed}) == "{expected}" ? toJson({parsed}) : {error}'
    )


def wrap(compiler, template, types):
    wrapper = {'name': compiler._template_name(template['name'] + '-validated')}
    for key in ('inputs', 'metadata'):
        if key in template:
            wrapper[key] = copy.deepcopy(template[key])
    for artifact in wrapper.get('inputs', {}).get('artifacts', []):
        artifact.pop('path', None)
    for annotation in (
        'pipelines.kubeflow.org/artifact-list-staging',
        'pipelines.kubeflow.org/staging-secret-volumes',
    ):
        wrapper.get('metadata', {}).get('annotations', {}).pop(annotation, None)
    for key in ('memoize', 'retryStrategy'):
        if key in template:
            wrapper[key] = template.pop(key)
    template.get('metadata', {}).get('annotations', {}).pop(
        'pipelines.kubeflow.org/cache-policy', None
    )
    wrapper.setdefault('metadata', {}).setdefault('annotations', {})[
        'pipelines.kubeflow.org/component-wrapper'
    ] = 'true'
    arguments = {}
    for field in ('parameters', 'artifacts'):
        if ports := template.get('inputs', {}).get(field):
            arguments[field] = [
                {
                    'name': port['name'],
                    'value' if field == 'parameters' else 'from': '{{inputs.'
                    + field
                    + '.'
                    + port['name']
                    + '}}',
                    **(
                        {'optional': True}
                        if field == 'artifacts' and port.get('optional')
                        else {}
                    ),
                }
                for port in ports
            ]
    checks = [
        {
            'name': name,
            'value': '{{='
            + expression(
                f'tasks["execute"].outputs.parameters[{json.dumps(name)}]', kind
            )
            + '}}',
        }
        for name, kind in types.items()
        if kind != 'String'
    ]
    validation = {
        'name': compiler._template_name(template['name'] + '-validate'),
        'inputs': {'parameters': [{'name': check['name']} for check in checks]},
        'suspend': {'duration': '0'},
    }
    compiler.templates.append(validation)
    # Output-evaluation errors on a DAG can lack outbound edges in Argo. Fail a
    # connected control node first so downstream tasks and the run terminate.
    wrapper['dag'] = {
        'tasks': [
            {
                'name': 'execute',
                'template': template['name'],
                'arguments': arguments,
            },
            {
                'name': 'validate',
                'template': validation['name'],
                'dependencies': ['execute'],
                'arguments': {'parameters': checks},
            },
        ]
    }
    wrapper['outputs'] = {}
    for field, ports in template.get('outputs', {}).items():
        wrapper['outputs'][field] = []
        for port in ports:
            name = port['name']
            reference = f'tasks["execute"].outputs.{field}[{json.dumps(name)}]'
            if field == 'parameters':
                kind = types.get(name, 'String')
                value = (
                    expression(reference, kind)
                    if kind != 'String'
                    else reference
                )
                output = {'name': name, 'valueFrom': {'expression': value}}
            else:
                output = {
                    'name': name,
                    'from': f'tasks.execute.outputs.artifacts.{name}',
                }
                if port.get('optional'):
                    output['optional'] = True
            wrapper['outputs'][field].append(output)
    compiler.templates.append(wrapper)
    return wrapper['name']
