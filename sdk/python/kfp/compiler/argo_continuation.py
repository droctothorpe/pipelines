# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Failure-aware task dependencies and optional upstream arguments."""

import re

from kfp.dsl import pipeline_channel, structures


def optional_after_failure(task, name, port):
    value = task.inputs.get(name)
    return (
        task._ignore_upstream_failure_tag
        and isinstance(value, pipeline_channel.PipelineChannel)
        and bool(value.task_name)
        and port.default is None
    )


def arguments(task, arguments):
    if not task._ignore_upstream_failure_tag:
        return
    from kfp.compiler.argo_compiler import _json, _kind
    from kfp.compiler.argo_groups import _expression_reference
    from kfp.dsl.argo_runtime import serialize

    parameters = {p['name']: p for p in arguments.get('parameters', [])}
    for name, port in (task.component_spec.inputs or {}).items():
        value = task.inputs.get(name)
        if (
            not isinstance(value, pipeline_channel.PipelineChannel)
            or not value.task_name
        ):
            continue
        parameter = structures.spec_type_is_parameter(port.type)
        reference = parameters[name if parameter else 'kfp-uri-' + name][
            'value'
        ]
        expression = _expression_reference(reference)
        source_task = re.search(r'(tasks\["[^"\\]+"\])\.outputs\.', expression)
        if source_task is None:
            raise ValueError(
                'Failure-tolerant inputs across group boundaries need optional group input lowering.'
            )
        present = f"{source_task[1]}.status == 'Succeeded'"
        if optional_after_failure(task, name, port):
            arguments['parameters'].append(
                {'name': 'kfp-present-' + name, 'value': '{{=' + present + '}}'}
            )
        for key in (
            [name] if parameter else ['kfp-uri-' + name, 'kfp-meta-' + name]
        ):
            item = parameters[key]
            source = _expression_reference(item['value'])
            fallback = (
                serialize(port.default, _kind(port))
                if parameter and port.default is not None
                else ''
            )
            # Argo checks missing references before evaluating a ternary; ?? guards that lookup.
            item['value'] = (
                '{{='
                + present
                + ' ? ('
                + source
                + ' ?? '
                + _json(fallback)
                + ') : '
                + _json(fallback)
                + '}}'
            )
        if not parameter:
            for item in arguments.get('artifacts', []):
                if item['name'] in (name, name + '-metadata'):
                    item['optional'] = True
                    # Defer missing-artifact lookup until Argo handles optional inputs.
                    item['from'] = item['from'][2:-2]


def dependencies(dag, ignored):
    """Keep every task a target so cleanup success cannot hide body failure."""
    from kfp.compiler.argo_compiler import _json

    changed = False
    for task in dag['tasks']:
        if task['name'] not in ignored:
            continue
        deps = task.get('dependencies', [])
        for name, port in (
            ignored[task['name']].component_spec.inputs or {}
        ).items():
            if port.type != 'PipelineTaskFinalStatus':
                continue
            failed = (
                ' || '.join(
                    f'tasks[{_json(dep)}].status in ["Failed", "Error", "Omitted"]'
                    for dep in deps
                )
                or 'false'
            )
            status = (
                "{{=toJson({'state': ("
                + failed
                + ") ? 'FAILED' : 'SUCCEEDED', 'pipeline_job_resource_name': workflow.uid, 'pipeline_task_name': "
                + _json(task['name'])
                + '})}}'
            )
            task.setdefault('arguments', {}).setdefault(
                'parameters', []
            ).append({'name': name, 'value': status})
        if not deps:
            continue
        task['depends'] = ' && '.join(
            '('
            + ' || '.join(
                f'{name}.{status}'
                for status in (
                    'Succeeded',
                    'Failed',
                    'Errored',
                    'Skipped',
                    'Omitted',
                )
            )
            + ')'
            for name in task.pop('dependencies')
        )
        changed = True
    if changed:
        dag['failFast'] = False
        dag['target'] = ' '.join(task['name'] for task in dag['tasks'])
