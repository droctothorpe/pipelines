# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Artifact-list staging templates and init-only repository credential
bindings."""

import copy
import json
import re
from pathlib import Path

MARKER = 'pipelines.kubeflow.org/artifact-list-staging'
BOUND = 'pipelines.kubeflow.org/staging-secret-volumes'
INIT = 'kfp-stage-artifacts'
ROOT = '/tmp/kfp/artifact-lists'


def staged_source(value, graph, inputs, seen=None):
    from kfp.compiler.argo_parameters import output_mapping
    from kfp.dsl import for_loop, pipeline_channel, structures

    if isinstance(value, for_loop.LoopArtifactArgument):
        return True
    if (
        not isinstance(value, pipeline_channel.PipelineArtifactChannel)
        or value.is_artifact_list
    ):
        return False
    if not value.task_name:
        return value.name in inputs
    task = graph.pipeline.tasks.get(value.task_name) if graph else None
    inner = task.component_spec.implementation.graph if task else None
    if not isinstance(inner, structures.CapturedGraph):
        return False
    seen = set() if seen is None else set(seen)
    key = (id(task), value.name)
    if key in seen:
        raise ValueError('Cyclic staged artifact reference.')
    seen.add(key)
    inner_inputs = {
        name
        for name, argument in task.inputs.items()
        if staged_source(argument, graph, inputs, seen)
    }
    return staged_source(
        output_mapping(inner).get(value.name), inner, inner_inputs, seen
    )


def add_staging(
    template, ports, metadata_location=None, command_expressions=None
):
    template.setdefault('metadata', {}).setdefault('annotations', {})[
        MARKER
    ] = 'v1'
    template.setdefault('inputs', {}).setdefault('artifacts', []).append(
        {
            'name': 'kfp-staging-inputs',
            'path': '/tmp/kfp/artifact-list-inputs.json',
            'raw': {'data': '{{inputs.parameters}}'},
        }
    )
    template.setdefault('volumes', []).extend(
        [
            {'name': 'kfp-artifact-lists', 'emptyDir': {}},
            {'name': 'kfp-stage-private-executor', 'emptyDir': {}},
        ]
    )
    template['container'].setdefault('volumeMounts', []).append(
        {'name': 'kfp-artifact-lists', 'mountPath': ROOT}
    )
    template.setdefault('initContainers', []).append(
        {
            'name': INIT,
            'image': 'python:3.11',
            'mirrorVolumeMounts': True,
            'command': [
                'python3',
                '-c',
                Path(__file__)
                .parents[1]
                .joinpath('dsl/argo_staging.py')
                .read_text(),
            ],
            'args': [json.dumps(ports, sort_keys=True)],
            'env': [
                {'name': 'KFP_STAGING_REPOSITORY', 'value': '{}'},
                {'name': 'ARGO_DEADLINE', 'value': '0001-01-01T00:00:00Z'},
                {'name': 'ARGO_WORKFLOW_NAME', 'value': '{{workflow.name}}'},
                {'name': 'ARGO_WORKFLOW_UID', 'value': '{{workflow.uid}}'},
                {'name': 'ARGO_CONTAINER_NAME', 'value': INIT},
                *[
                    {
                        'name': name,
                        'valueFrom': {'fieldRef': {'fieldPath': field}},
                    }
                    for name, field in (
                        ('ARGO_POD_NAME', 'metadata.name'),
                        ('ARGO_POD_UID', 'metadata.uid'),
                        (
                            'ARGO_NODE_ID',
                            "metadata.annotations['workflows.argoproj.io/node-id']",
                        ),
                    )
                ],
            ],
            'volumeMounts': [
                {
                    'name': 'kfp-artifact-lists',
                    'mountPath': '/argo/inputs/artifacts',
                },
            ],
        }
    )
    # Argo adds this executor volume itself; user init mount validation runs
    # before that addition. PodSpecPatch binds it after the volume exists.
    patch = json.loads(template.get('podSpecPatch', '{}'))
    init = template['initContainers'][-1]
    patch.setdefault('initContainers', []).append(
        {
            'name': INIT,
            'command': init['command'],
            'volumeMounts': [
                {
                    'name': 'var-run-argo',
                    'mountPath': '/kfp-argo-binary',
                    'readOnly': True,
                },
                {
                    'name': 'kfp-stage-private-executor',
                    'mountPath': '/var/run/argo',
                },
            ],
        }
    )
    if metadata_location is not None:
        from kfp.compiler.argo_structured import expression

        container = template['container']
        command = container.get('command', [])
        command_expression = (command_expressions or {}).get('command')
        if (not command and not command_expression) or (
            command and '__KFP_LIST_' in command[0]
        ):
            raise ValueError(
                'Raw artifact-list consumers currently require an explicit executable command.'
            )
        arguments = command[1:] + container.get('args', [])
        argument_expression = (
            'flatten([('
            + command_expression
            + ')[1:],'
            + command_expressions['args']
            + '])'
            if command_expression
            else expression(arguments)
        )
        summary = next(
            p
            for p in template['outputs']['parameters']
            if p['name'] == 'kfp-metadata'
        )
        template['inputs']['artifacts'].extend(
            [
                {
                    'name': 'kfp-staging-args',
                    'path': '/tmp/kfp/artifact-list-args.json',
                    'raw': {'data': '{{=toJson(' + argument_expression + ')}}'},
                },
                {
                    'name': 'kfp-staging-summary',
                    'path': '/tmp/kfp/artifact-list-summary.json',
                    'raw': {'data': summary['value']},
                },
            ]
        )
        template['outputs']['parameters'] = [
            p
            for p in template['outputs']['parameters']
            if p['name'] != 'kfp-metadata'
        ]
        for parameter in template['outputs']['parameters']:
            if parameter['name'].startswith('kfp-meta-'):
                port = parameter['name'].removeprefix('kfp-meta-')
                parameter.pop('value', None)
                parameter['valueFrom'] = {
                    'path': ROOT + '/identity-' + port + '.json'
                }
        for artifact in template['outputs'].get('artifacts', []):
            if artifact['name'].endswith('-metadata'):
                artifact['path'] = (
                    ROOT
                    + '/metadata-'
                    + artifact['name'].removesuffix('-metadata')
                    + '.json'
                )
        template['outputs'].setdefault('artifacts', []).append(
            {
                'name': 'kfp-metadata',
                'path': ROOT + '/metadata.json',
                'archive': {'none': {}},
                **metadata_location,
            }
        )
        init['args'].append('--raw')
        container['command'] = (
            ['{{=(' + command_expression + ')[0]}}']
            if command_expression
            else command[:1]
        )
        container['args'] = []
        container.setdefault('env', []).append(
            {'name': 'ARGO_CONTAINER_ARGS_FILE', 'value': ROOT + '/args.json'}
        )
        main = next(
            (c for c in patch.get('containers', []) if c['name'] == 'main'),
            None,
        )
        if main is None:
            main = {'name': 'main'}
            patch.setdefault('containers', []).append(main)
        main['args'] = []
    template['podSpecPatch'] = json.dumps(patch)


def needs_binding(spec):
    return any(
        t.get('metadata', {}).get('annotations', {}).get(MARKER) == 'v1'
        for t in spec.get('templates', [])
    )


def bind_repository(spec, repository):
    """Use Secret references only; never read Secret values or mount them in
    main."""
    repository = {
        k: copy.deepcopy(v) for k, v in repository.items() if k in ('s3', 'gcs')
    }
    secrets = {}
    for config in repository.values():
        if not isinstance(config, dict):
            raise ValueError('Invalid artifact-repository configuration.')
        for field, selector in config.items():
            if not field.endswith('Secret') or not selector:
                continue
            if not isinstance(selector, dict):
                raise ValueError('Invalid artifact-repository Secret selector.')
            name, key = selector.get('name', ''), selector.get('key', '')
            if not isinstance(name, str) or not isinstance(key, str):
                raise ValueError('Invalid artifact-repository Secret selector.')
            if (
                not re.fullmatch(r'[a-z0-9][a-z0-9.-]*', name)
                or not re.fullmatch(r'[A-Za-z0-9_.-]+', key)
                or key in ('.', '..')
            ):
                raise ValueError('Invalid artifact-repository Secret selector.')
            secrets.setdefault(name, set()).add(key)
    for template in spec.get('templates', []):
        annotations = template.get('metadata', {}).get('annotations', {})
        if annotations.get(MARKER) != 'v1':
            continue
        init = next(c for c in template['initContainers'] if c['name'] == INIT)
        previous = set(json.loads(annotations.get(BOUND, '[]')))
        template['volumes'] = [
            v for v in template.get('volumes', []) if v['name'] not in previous
        ]
        init['volumeMounts'] = [
            v for v in init['volumeMounts'] if v['name'] not in previous
        ]
        bound = []
        for index, (name, keys) in enumerate(sorted(secrets.items())):
            volume = 'kfp-stage-secret-' + str(index)
            if any(v['name'] == volume for v in template['volumes']):
                raise ValueError(
                    'Artifact staging volume conflicts with an existing volume.'
                )
            template['volumes'].append(
                {
                    'name': volume,
                    'secret': {
                        'secretName': name,
                        'items': [
                            {'key': key, 'path': key} for key in sorted(keys)
                        ],
                    },
                }
            )
            init['volumeMounts'].append(
                {
                    'name': volume,
                    'mountPath': '/argo/secret/' + name,
                    'readOnly': True,
                }
            )
            bound.append(volume)
        annotations[BOUND] = json.dumps(bound)
        next(e for e in init['env'] if e['name'] == 'KFP_STAGING_REPOSITORY')[
            'value'
        ] = json.dumps(repository, allow_nan=False)
