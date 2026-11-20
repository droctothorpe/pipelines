# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Lower captured DSL objects directly to Argo templates (no PipelineSpec
IR)."""

import copy
import dataclasses
import graphlib
import hashlib
import json
import re
import warnings
from pathlib import Path

import kfp
from kfp.compiler import argo_continuation, argo_parameters
from kfp.compiler.argo_artifacts import (
    BUCKET,
    PREFIX,
    ROOT,
    reference,
    root_annotations,
)
from kfp.dsl import (
    for_loop,
    pipeline_channel,
    pipeline_task,
    structures,
    tasks_group,
)
from kfp.dsl.argo_runtime import SCHEMA, serialize
from kfp.dsl.types import type_utils


def _json(value):
    return json.dumps(
        value, sort_keys=True, separators=(',', ':'), allow_nan=False
    )


def _bound_to_parameters(value):
    if isinstance(value, dict):
        return any(
            key in ('componentInputParameter', 'taskOutputParameter')
            for key in value
        ) or any(_bound_to_parameters(item) for item in value.values())
    if isinstance(value, list):
        return any(_bound_to_parameters(item) for item in value)
    return False


def _merge_settings(target, source):
    for key, value in source.items():
        current = target.get(key)
        if isinstance(value, dict) and isinstance(current, dict):
            _merge_settings(current, value)
        elif isinstance(value, list) and isinstance(current, list):
            current.extend(value)
        else:
            target[key] = value


def _kind(port):
    if not structures.spec_type_is_parameter(port.type):
        return port.type
    name = type_utils.get_canonical_name_for_outer_generic(port.type).lower()
    kinds = {
        'str': 'String',
        'string': 'String',
        'int': 'Integer',
        'integer': 'Integer',
        'float': 'Float',
        'double': 'Float',
        'bool': 'Boolean',
        'boolean': 'Boolean',
        'list': 'List',
        'dict': 'Dict',
        'pipelinetaskfinalstatus': 'Dict',
        'taskconfig': 'Dict',
    }
    if name not in kinds:
        raise ValueError(
            f'Unsupported parameter type {port.type!r}; use a supported scalar, list or dict.'
        )
    return kinds[name]


def _ref(scope, name):
    return '{{' + scope + '.' + name + '}}'


def local_image_reference(image: str, digest: str) -> str:
    """Name a local image snapshot by its verified Docker build identity."""
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', digest):
        raise ValueError('Local image identity must be a full sha256 digest.')
    repository = image.split('@')[0]
    if repository.rfind(':') > repository.rfind('/'):
        repository = repository[: repository.rfind(':')]
    return repository + ':kfp-' + digest.removeprefix('sha256:')


def _name(value):
    return re.sub('[^a-z0-9-]', '-', value.lower()).strip('-') or 'pipeline'


class _Compiler:
    def __init__(self, options, pipeline_name):
        self.options = options
        self.pipeline_name = pipeline_name
        self.templates = []
        # Enclosing nested-pipeline tasks, outermost first, while compiling a sub-pipeline.
        self.nested_tasks = []
        self.extra_inputs = {}
        self.disable_caching = options.disable_caching
        self.artifact_previews = True
        self.workspace = None
        self.graph_context = (None, None)
        self.staged_graph_inputs = set()
        self.root_annotations = root_annotations(options.artifact_repository)
        self.driver = (
            's3' if options.artifact_repository.startswith('s3:') else 'gcs'
        )
        self.bucket = reference(BUCKET)
        self.prefix = reference(PREFIX)
        self.uri = reference(ROOT)

    def _template_name(self, name):
        return f't{len(self.templates)}-{_name(name)[:45]}'

    def workspace_value(self, value):
        if '{{$.workspace_path}}' in value:
            if self.workspace is None:
                raise ValueError(
                    'Workspace path requires PipelineConfig(workspace=...).'
                )
            value = value.replace('{{$.workspace_path}}', '/kfp-workspace')
        return value

    def value(self, value, field='parameters', suffix=''):
        if isinstance(value, pipeline_channel.PipelineChannel):
            scope = (
                f'tasks.{value.task_name}.outputs'
                if value.task_name
                else 'inputs'
            )
            return _ref(scope + '.' + field, value.name + suffix)
        if isinstance(value, str):
            value = self.workspace_value(value)
            for (
                channel
            ) in pipeline_channel.extract_pipeline_channels_from_string(value):
                value = value.replace(str(channel), self.value(channel))
            return value
        return _json(value)

    def staged_source(self, channel):
        from kfp.compiler.argo_artifact_lists import staged_source

        return staged_source(
            channel, self.graph_context[1], self.staged_graph_inputs
        )

    def workspace_import(self, channel):
        """True when the artifact comes from an importer in the same graph that
        downloads into the shared workspace."""
        if (
            self.workspace is None
            or not isinstance(channel, pipeline_channel.PipelineArtifactChannel)
            or not channel.task_name
        ):
            return False
        graph = self.graph_context[1]
        producer = (
            graph.pipeline.tasks.get(channel.task_name) if graph else None
        )
        importer = (
            producer.component_spec.implementation.importer
            if producer
            else None
        )
        return bool(importer and importer.download_to_workspace)

    def nullable_source(self, channel):
        return argo_parameters.source_nullable(channel, *self.graph_context)

    def argument_value(self, value, port, task, resolver=None):
        return argo_parameters.bind(
            value,
            port,
            resolver or self.value,
            self.nullable_source,
        )

    def compile_component(self, component_spec, task=None):
        graph = component_spec.implementation.graph
        if graph is not None:
            if not isinstance(graph, structures.CapturedGraph):
                raise ValueError(
                    'Precompiled KFP IR graphs are not supported; compile the original Python pipeline.'
                )
            if task and task._task_spec.retry_policy:
                # Stock compiles the policy into the DAG task but never applies
                # it: its Argo compiler neutralizes DAG retries because retrying
                # a DAG re-runs the whole subgraph and nested DAGs multiply that.
                warnings.warn(
                    f'Retry policy on nested pipeline task {task.name!r} is ignored, as in stock KFP: '
                    'a sub-pipeline is not retried as a whole. Set retries on its inner tasks.',
                    stacklevel=2,
                )
            inherited = self.disable_caching
            previous_graph = self.graph_context
            previous_staged = self.staged_graph_inputs
            staged = (
                {
                    name
                    for name, value in task.inputs.items()
                    if self.staged_source(value)
                }
                if task
                else set()
            )
            self.graph_context = (component_spec, graph)
            self.staged_graph_inputs = staged
            self.disable_caching = inherited or bool(
                task and not task._task_spec.enable_caching
            )
            if task:
                self.nested_tasks.append(task)
            try:
                name = self.graph(component_spec, graph)
                target = next(
                    template
                    for template in self.templates
                    if template['name'] == name
                )
                annotations = target.setdefault('metadata', {}).setdefault(
                    'annotations', {}
                )
                annotations['pipelines.kubeflow.org/input-parameter-types'] = (
                    _json(
                        {
                            key: argo_parameters.input_kind(port)
                            for key, port in (
                                component_spec.inputs or {}
                            ).items()
                            if structures.spec_type_is_parameter(port.type)
                        }
                    )
                )
                returned = argo_parameters.output_mapping(graph)
                annotations['pipelines.kubeflow.org/output-parameter-types'] = (
                    _json(
                        {
                            key: (
                                'Nullable'
                                if self.nullable_source(returned.get(key))
                                else ''
                            )
                            + _kind(port)
                            for key, port in (
                                component_spec.outputs or {}
                            ).items()
                            if structures.spec_type_is_parameter(port.type)
                        }
                    )
                )
                graph_display_name = (
                    task._task_spec.display_name if task else None
                ) or graph.display_name
                if graph_display_name:
                    target.setdefault('metadata', {}).setdefault(
                        'annotations', {}
                    )['workflows.argoproj.io/display-name'] = graph_display_name
                return name
            finally:
                if task:
                    self.nested_tasks.pop()
                self.disable_caching = inherited
                self.graph_context = previous_graph
                self.staged_graph_inputs = previous_staged
        if component_spec.implementation.importer is not None:
            from kfp.compiler.argo_importer import compile_importer

            return compile_importer(
                self, task or pipeline_task.PipelineTask(component_spec, {})
            )
        if task is None:
            task = pipeline_task.PipelineTask(component_spec, {})
        return self.leaf(task)

    def graph(self, component_spec, graph):
        root = graph.pipeline.groups[0]
        if root.groups:
            from kfp.compiler.argo_groups import compile_graph

            return compile_graph(self, component_spec, graph)
        template = {
            'name': self._template_name(component_spec.name),
            'dag': {'tasks': []},
        }
        self.templates.append(template)
        inputs = {'parameters': [], 'artifacts': []}
        for name, port in (component_spec.inputs or {}).items():
            self.input_port(
                inputs, name, port, staged=name in self.staged_graph_inputs
            )
        if any(inputs.values()):
            template['inputs'] = {
                key: value for key, value in inputs.items() if value
            }
        dependencies = {}
        for task in root.tasks:
            target = self.compile_component(task.component_spec, task)
            arguments = {'parameters': [], 'artifacts': []}
            for name, port in (task.component_spec.inputs or {}).items():
                if name in task.inputs:
                    value = task.inputs[name]
                elif port.optional and port.default is not None:
                    value = port.default
                elif port.optional:
                    continue
                else:
                    raise ValueError(
                        f'Task {task.name!r} is missing input {name!r}.'
                    )
                if port.is_artifact_list or self.staged_source(value):
                    scope = (
                        f'tasks.{value.task_name}.outputs.parameters'
                        if value.task_name
                        else 'inputs.parameters'
                    )
                    arguments['parameters'].extend(
                        {
                            'name': prefix + name,
                            'value': _ref(scope, prefix + value.name),
                        }
                        for prefix in ('kfp-uri-', 'kfp-meta-')
                    )
                elif structures.spec_type_is_parameter(port.type):
                    arguments['parameters'].append(
                        {
                            'name': name,
                            'value': self.argument_value(value, port, task),
                        }
                    )
                else:
                    if not isinstance(
                        value, pipeline_channel.PipelineArtifactChannel
                    ):
                        raise ValueError(
                            f'Artifact {name!r} must come from an upstream output or typed pipeline input.'
                        )
                    scope = (
                        f'tasks.{value.task_name}.outputs.parameters'
                        if value.task_name
                        else 'inputs.parameters'
                    )
                    arguments['artifacts'].extend(
                        [
                            {
                                'name': name,
                                'from': self.value(value, 'artifacts'),
                            },
                            {
                                'name': name + '-metadata',
                                'from': self.value(
                                    value, 'artifacts', '-metadata'
                                ),
                                'optional': True,
                            },
                        ]
                    )
                    for prefix in ('kfp-uri-', 'kfp-meta-'):
                        arguments['parameters'].append(
                            {
                                'name': prefix + name,
                                'value': _ref(scope, prefix + value.name),
                            }
                        )
            arguments['parameters'].extend(
                {
                    'name': name,
                    'value': self.argument_value(
                        channel,
                        structures.InputSpec(type=channel.channel_type),
                        task,
                    ),
                }
                for name, channel in self.extra_inputs.get(id(task), [])
            )
            argo_continuation.arguments(task, arguments)
            deps = set(task.dependent_tasks)
            deps.update(
                channel.task_name
                for _, channel in self.extra_inputs.get(id(task), [])
                if channel.task_name
            )
            deps.update(
                channel.task_name
                for channel in task.channel_inputs
                if channel.task_name
            )
            dependencies[task.name] = deps
            dag_task = {'name': task.name, 'template': target}
            if deps:
                dag_task['dependencies'] = sorted(deps)
            if any(arguments.values()):
                dag_task['arguments'] = {
                    key: value for key, value in arguments.items() if value
                }
            template['dag']['tasks'].append(dag_task)
        argo_continuation.dependencies(
            template['dag'],
            {
                task.name: task
                for task in root.tasks
                if task._ignore_upstream_failure_tag
            },
        )
        missing = (
            set().union(*dependencies.values()) - set(dependencies)
            if dependencies
            else set()
        )
        if missing:
            raise ValueError(
                f'Task dependencies cross an unsupported scope: {sorted(missing)}.'
            )
        try:
            tuple(graphlib.TopologicalSorter(dependencies).static_order())
        except graphlib.CycleError as error:
            raise ValueError(
                'Pipeline has a dependency cycle; remove the cyclic .after() or data dependency.'
            ) from error
        outputs = graph.outputs
        if outputs is not None:
            if hasattr(outputs, '_asdict'):
                outputs = outputs._asdict()
            elif not isinstance(outputs, dict):
                outputs = {'Output': outputs}
            template['outputs'] = {'parameters': [], 'artifacts': []}
            for name, value in outputs.items():
                port = component_spec.outputs[name]
                if not isinstance(value, pipeline_channel.PipelineChannel):
                    raise ValueError(
                        'Pipeline outputs must reference task output channels.'
                    )
                if port.is_artifact_list or self.staged_source(value):
                    scope = (
                        f'tasks.{value.task_name}.outputs.parameters'
                        if value.task_name
                        else 'inputs.parameters'
                    )
                    for prefix in ('kfp-uri-', 'kfp-meta-'):
                        reference = _ref(scope, prefix + value.name)
                        from kfp.compiler.argo_groups import _parameter_source

                        template['outputs']['parameters'].append(
                            {
                                'name': prefix + name,
                                'valueFrom': _parameter_source(reference),
                            }
                        )
                elif structures.spec_type_is_parameter(port.type):
                    template['outputs']['parameters'].append(
                        {
                            'name': name,
                            'valueFrom': (
                                {'parameter': self.value(value)}
                                if value.task_name
                                else {
                                    'expression': 'inputs.parameters['
                                    + _json(value.name)
                                    + ']'
                                }
                            ),
                        }
                    )
                else:
                    template['outputs']['artifacts'].extend(
                        [
                            {
                                'name': name,
                                'from': self.value(value, 'artifacts'),
                            },
                            {
                                'name': name + '-metadata',
                                'from': self.value(
                                    value, 'artifacts', '-metadata'
                                ),
                                'optional': True,
                            },
                        ]
                    )
                    for prefix in ('kfp-uri-', 'kfp-meta-'):
                        template['outputs']['parameters'].append(
                            {
                                'name': prefix + name,
                                'valueFrom': {
                                    'parameter': _ref(
                                        f'tasks.{value.task_name}.outputs.parameters',
                                        prefix + value.name,
                                    )
                                },
                            }
                        )
            template['outputs'] = {
                key: value
                for key, value in template['outputs'].items()
                if value
            }
        return template['name']

    def input_port(self, inputs, name, port, allow_nullable=True, staged=False):
        if port.is_artifact_list or staged:
            inputs['parameters'].extend(
                {'name': prefix + name} for prefix in ('kfp-uri-', 'kfp-meta-')
            )
            return
        if structures.spec_type_is_parameter(port.type):
            item = {'name': name}
            if port.type == 'TaskConfig':
                item['default'] = '{}'
            elif allow_nullable and argo_parameters.nullable(port):
                item['default'] = 'null'
            if port.optional and port.default is not None:
                item['default'] = self.value(
                    serialize(port.default, _kind(port))
                )
            inputs['parameters'].append(item)
        else:
            inputs['artifacts'].extend(
                [
                    {'name': name, 'path': '/tmp/kfp/inputs/' + name},
                    {
                        'name': name + '-metadata',
                        'path': '/tmp/kfp/inputs/' + name + '.json',
                        'optional': True,
                    },
                ]
            )
            inputs['parameters'].extend(
                [{'name': 'kfp-uri-' + name}, {'name': 'kfp-meta-' + name}]
            )

    def leaf(self, task):
        container = task.container_spec
        if container is None:
            raise ValueError(
                f'Component {task.name!r} has no supported container implementation.'
            )
        fresh_pvc = container.image == 'argostub/createpvc' and (
            not isinstance(task.inputs.get('pvc_name'), str)
            or not task.inputs.get('pvc_name')
        )
        # The PVC stubs read the whole parameter map as JSON, so their argv never
        # depends on which nullable inputs are present.
        pvc_stub = container.image in (
            'argostub/createpvc',
            'argostub/deletepvc',
        )
        if pvc_stub:
            operation = (
                'create'
                if container.image == 'argostub/createpvc'
                else 'delete'
            )
            container = dataclasses.replace(
                container,
                image='python:3.11',
                command=[
                    'sh',
                    '-c',
                    'python -m pip install --quiet "kubernetes>=37.0.2" && exec python -c "$0" "$@"',
                    Path(__file__).with_name('argo_pvc.py').read_text(),
                ],
                args=[
                    operation,
                    '{{inputs.parameters}}',
                    '{{workflow.namespace}}',
                    # Names the stub must JSON-decode; the rest arrive raw.
                    _json(
                        sorted(
                            name
                            for name, port in (
                                task.component_spec.inputs or {}
                            ).items()
                            if argo_parameters.nullable(port)
                            or _kind(port) in ('List', 'Dict')
                        )
                    ),
                ]
                + (
                    ["{{$.outputs.parameters['name'].output_file}}"]
                    if operation == 'create'
                    else []
                ),
            )
        if any(
            name.startswith('KFP_DEBUG_PAUSE_')
            for name in (container.env or {})
        ):
            raise ValueError(
                'KFP launcher debug pauses are unavailable; add a native Argo suspend template instead.'
            )
        template = {'name': self._template_name(task.name)}
        self.templates.append(template)
        spec = task.component_spec
        args = list(container.args or [])
        python = '--executor_input' in args and '{{$}}' in args
        inputs = {'parameters': [], 'artifacts': []}
        outputs = {'parameters': [], 'artifacts': []}
        contract = {
            'schema': SCHEMA,
            'artifactPreviews': self.artifact_previews,
            'outputDirectory': '/tmp/kfp/outputs',
            'inputs': {},
            'outputs': {},
        }
        replacements = {}
        workspace_inputs = False
        for name, port in (spec.inputs or {}).items():
            if (
                port.optional
                and port.default is None
                and name not in task.inputs
                and port.type not in ('PipelineTaskFinalStatus', 'TaskConfig')
            ):
                continue
            staged = self.staged_source(task.inputs.get(name))
            self.input_port(inputs, name, port, staged=staged)
            declaration = {'type': argo_parameters.input_kind(port)}
            if port.type == 'TaskConfig':
                declaration['taskConfig'] = True
            if port.is_artifact_list or staged:
                if staged:
                    replacements[
                        f"{{{{$.inputs.artifacts['{name}'].path}}}}"
                    ] = '__KFP_PATH_' + name + '__'
                    replacements[
                        f"{{{{$.inputs.artifacts['{name}'].uri}}}}"
                    ] = _ref('inputs.parameters', 'kfp-uri-' + name)
                replacements[f"{{{{$.inputs.artifacts['{name}']}}}}"] = (
                    '__KFP_LIST_' + name + '__'
                )
                declaration['stagedArtifact' if staged else 'artifactList'] = (
                    True
                )
                declaration['manifestPath'] = (
                    '/tmp/kfp/artifact-lists/manifest.json'
                )
                contract['inputs'][name] = declaration
                continue
            if argo_continuation.optional_after_failure(task, name, port):
                # Python components read the flag through the bridge; raw
                # containers get it as the IfPresent condition in their argv.
                declaration['presenceParameter'] = 'kfp-present-' + name
                inputs['parameters'].append(
                    {'name': declaration['presenceParameter']}
                )
                for artifact in inputs['artifacts']:
                    if artifact['name'] == name:
                        artifact['optional'] = True
            if structures.spec_type_is_parameter(port.type):
                declaration['optional'] = port.optional
                supplied = task.inputs.get(name)
                if isinstance(supplied, for_loop.Collected):
                    if supplied.is_artifact_channel:
                        raise ValueError(
                            'Collected artifact lists require native multi-artifact staging.'
                        )
                    declaration['collectionElementType'] = (
                        'Nullable'
                        if self.nullable_source(supplied.output)
                        else ''
                    ) + _kind(
                        structures.InputSpec(type=supplied.output.channel_type)
                    )
                    consumer_groups = set()
                    parent = task.parent_task_group
                    while parent is not None:
                        consumer_groups.add(id(parent))
                        parent = parent.parent_task_group
                    depth = 0
                    parent = supplied.output.task.parent_task_group
                    while (
                        parent is not None and id(parent) not in consumer_groups
                    ):
                        depth += isinstance(parent, tasks_group.ParallelFor)
                        parent = parent.parent_task_group
                    declaration['collectionDepth'] = depth
                value_reference = _ref('inputs.parameters', name)
                if (
                    not python
                    and argo_parameters.nullable(port)
                    and _kind(port) == 'String'
                ):
                    parameter = 'inputs.parameters[' + _json(name) + ']'
                    value_reference = (
                        '{{='
                        + parameter
                        + " == 'null' ? 'null' : fromJSON("
                        + parameter
                        + ')}}'
                    )
                replacements[f"{{{{$.inputs.parameters['{name}']}}}}"] = (
                    value_reference
                )
            else:
                declaration.update(
                    path='/tmp/kfp/inputs/' + name,
                    metadataPath='/tmp/kfp/inputs/' + name + '.json',
                )
                path_reference = declaration['path']
                if self.workspace_import(task.inputs.get(name)):
                    # The importer already placed the payload on the shared
                    # workspace; read it there instead of staging a second copy.
                    from kfp.compiler.argo_importer import workspace_target

                    inputs['artifacts'] = [
                        item
                        for item in inputs['artifacts']
                        if item['name'] not in (name, name + '-metadata')
                    ]
                    declaration['workspace'] = True
                    workspace_inputs = True
                    path_reference = (
                        '{{='
                        + workspace_target(
                            'inputs.parameters['
                            + _json('kfp-uri-' + name)
                            + ']'
                        )
                        + '}}'
                    )
                replacements[f"{{{{$.inputs.artifacts['{name}'].path}}}}"] = (
                    path_reference
                )
                replacements[f"{{{{$.inputs.artifacts['{name}'].uri}}}}"] = (
                    _ref('inputs.parameters', 'kfp-uri-' + name)
                )
            contract['inputs'][name] = declaration
        for name, port in (spec.outputs or {}).items():
            path = '/tmp/kfp/outputs/' + name
            declaration = {'type': _kind(port), 'path': path}
            if structures.spec_type_is_parameter(port.type):
                outputs['parameters'].append(
                    {'name': name, 'valueFrom': {'path': path}}
                )
                replacements[
                    f"{{{{$.outputs.parameters['{name}'].output_file}}}}"
                ] = path
            else:
                key = self.prefix + '/'.join(
                    ['{{workflow.uid}}', '{{pod.name}}', name]
                )
                uri = self.uri + '/{run}/{task}/' + name
                declaration.update(
                    metadataPath='/tmp/kfp/metadata/' + name + '.json',
                    identityPath='/tmp/kfp/identities/' + name + '.json',
                    metadataUri=self.uri
                    + '/{run}/{task}/metadata/'
                    + name
                    + '.json',
                    uri=uri,
                )
                outputs['artifacts'].extend(
                    [
                        {
                            'name': name,
                            'path': path,
                            'archive': {'none': {}},
                            self.driver: {'bucket': self.bucket, 'key': key},
                        },
                        {
                            'name': name + '-metadata',
                            'path': declaration['metadataPath'],
                            'archive': {'none': {}},
                            self.driver: {
                                'bucket': self.bucket,
                                'key': self.prefix
                                + '/'.join(
                                    [
                                        '{{workflow.uid}}',
                                        '{{pod.name}}',
                                        'metadata',
                                        name + '.json',
                                    ]
                                ),
                            },
                        },
                    ]
                )
                outputs['parameters'].append(
                    {
                        'name': 'kfp-uri-' + name,
                        'value': self.uri
                        + '/{{workflow.uid}}/{{pod.name}}/'
                        + name,
                    }
                )
                replacements[f"{{{{$.outputs.artifacts['{name}'].path}}}}"] = (
                    path
                )
                replacements[f"{{{{$.outputs.artifacts['{name}'].uri}}}}"] = (
                    self.uri + '/{{workflow.uid}}/{{pod.name}}/' + name
                )
            contract['outputs'][name] = declaration
        if python:
            index = args.index('--executor_input')
            if args[index + 1] != '{{$}}':
                raise ValueError(
                    f'Task {task.name!r} has a nonstandard executor input; use a standard Python component.'
                )
            args[index : index + 2] = [
                '--argo_input',
                _json(contract),
                *(
                    [
                        '--argo_parameters_file',
                        '/tmp/kfp/artifact-list-inputs.json',
                    ]
                    if any(
                        port.get('artifactList') or port.get('stagedArtifact')
                        for port in contract['inputs'].values()
                    )
                    else [
                        '--argo_parameters',
                        '{{inputs.parameters}}'
                        if inputs['parameters']
                        else '[]',
                    ]
                ),
            ]
            outputs['artifacts'].append(
                {
                    'name': 'kfp-metadata',
                    'path': '/tmp/kfp/outputs/metadata.json',
                    'archive': {'none': {}},
                    self.driver: {
                        'bucket': self.bucket,
                        'key': self.prefix
                        + '{{workflow.uid}}/{{pod.name}}/kfp-metadata.json',
                    },
                }
            )
            for name, port in contract['outputs'].items():
                if 'metadataPath' in port:
                    if self.artifact_previews:
                        original = next(
                            item
                            for item in outputs['artifacts']
                            if item['name'] == name
                        )
                        location = dict(original[self.driver])
                        location['key'] += '.kfp-preview.json'
                        outputs['artifacts'].append(
                            {
                                'name': name + '-preview',
                                'path': port['path'] + '.kfp-preview.json',
                                'optional': True,
                                'archive': {'none': {}},
                                self.driver: location,
                            }
                        )
                    outputs['parameters'].append(
                        {
                            'name': 'kfp-meta-' + name,
                            'valueFrom': {'path': port['identityPath']},
                        }
                    )
        else:
            self.native_metadata(template, contract, outputs)
            # Container images need not contain Python or a shell. Use /tmp,
            # which already exists, rather than requiring a wrapper mkdir.
            for declaration in contract['outputs'].values():
                old = declaration['path']
                new = '/tmp/kfp-' + old.rsplit('/', 1)[-1]
                replacements = {
                    key: value.replace(old, new)
                    for key, value in replacements.items()
                }
                for output in outputs['parameters']:
                    if output.get('valueFrom', {}).get('path') == old:
                        output['valueFrom']['path'] = new
                for output in outputs['artifacts']:
                    if output.get('path') == old:
                        output['path'] = new

        def convert(value):
            if isinstance(value, pipeline_channel.PipelineChannel):
                value = str(value)
            elif not isinstance(value, str):
                value = _json(value)
            for old, new in replacements.items():
                value = value.replace(old, new)
            value = self.workspace_value(value)
            if '{{$.' in value or '{{$}}' in value:
                raise ValueError(
                    f'Task {task.name!r} contains an unsupported KFP placeholder; replace it with a supported parameter/path.'
                )
            return value

        def command_elements(value):
            if isinstance(value, str) and (
                value.startswith('{"Concat":')
                or value.startswith('{"IfPresent":')
            ):
                value = json.loads(value)
            if isinstance(value, dict) and 'Concat' in value:
                return [
                    ''.join(
                        part
                        for item in value['Concat']
                        for part in command_elements(item)
                    )
                ]
            if isinstance(value, dict) and 'IfPresent' in value:
                declaration = value['IfPresent']
                name = declaration['InputName']
                present = (
                    name in task.inputs
                    or name in (spec.outputs or {})
                    or (
                        name in (spec.inputs or {})
                        and spec.inputs[name].default is not None
                    )
                )
                branch = declaration.get('Then' if present else 'Else', [])
                return [
                    part
                    for item in (
                        branch if isinstance(branch, list) else [branch]
                    )
                    for part in command_elements(item)
                ]
            return [convert(value)]

        digest = self.options.image_digests.get(container.image)
        rendered = {
            'image': local_image_reference(container.image, digest)
            if digest
            else container.image
        }
        if container.command:
            rendered['command'] = [
                part
                for value in container.command
                for part in command_elements(value)
            ]
        if python:
            from kfp.compiler.argo_bootstrap import portable_command

            rendered['command'] = portable_command(
                rendered.get('command'),
                artifact_previews=self.artifact_previews
                and any(
                    'metadataPath' in port
                    for port in contract['outputs'].values()
                ),
            )
        if args:
            rendered['args'] = [
                part for value in args for part in command_elements(value)
            ]
        rendered['env'] = [
            {'name': name, 'value': convert(value)}
            for name, value in (container.env or {}).items()
        ]
        if python:
            rendered['env'].extend(
                [
                    {'name': 'KFP_ARGO_RUN_UID', 'value': '{{workflow.uid}}'},
                    {
                        'name': 'KFP_ARGO_WORKFLOW_NAME',
                        'value': '{{workflow.name}}',
                    },
                    {'name': 'KFP_ARGO_NODE_ID', 'value': '{{pod.name}}'},
                    {
                        'name': 'KFP_ARGO_NAMESPACE',
                        'value': '{{workflow.namespace}}',
                    },
                ]
            )
        if container.resources:
            resources = dataclasses.asdict(container.resources)
            rendered['resources'] = {}
            for suffix, target in [
                ('request', 'requests'),
                ('limit', 'limits'),
            ]:
                values = {
                    kind: resources[kind + '_' + suffix]
                    for kind in ('cpu', 'memory')
                    if resources[kind + '_' + suffix] is not None
                }
                if values:
                    rendered['resources'][target] = values
            if resources['accelerator_count'] or resources['accelerator_type']:
                if (
                    not resources['accelerator_type']
                    or not resources['accelerator_count']
                ):
                    raise ValueError(
                        'Set both accelerator type and count for native GPU resources.'
                    )
                rendered['resources'].setdefault('limits', {})[
                    resources['accelerator_type']
                ] = resources['accelerator_count']
        template['container'] = rendered
        command_expressions = None
        if (
            not python
            and not pvc_stub
            and (
                any(
                    argo_parameters.nullable(port)
                    or argo_continuation.optional_after_failure(
                        task, name, port
                    )
                    for name, port in (spec.inputs or {}).items()
                )
                or (
                    any(
                        port.is_artifact_list
                        for port in (spec.inputs or {}).values()
                    )
                    and 'IfPresent' in _json([container.command, args])
                )
            )
        ):
            from kfp.compiler.argo_commands import arguments

            presence = {name: True for name in (spec.outputs or {})}
            for name, port in (spec.inputs or {}).items():
                if name not in contract['inputs']:
                    presence[name] = False
                elif argo_continuation.optional_after_failure(task, name, port):
                    # Absent once its producer failed, whatever value was forwarded.
                    presence[name] = (
                        'inputs.parameters['
                        + _json('kfp-present-' + name)
                        + "] == 'true'"
                    )
                elif port.is_artifact_list:
                    presence[name] = (
                        'len(fromJSON(inputs.parameters['
                        + _json('kfp-meta-' + name)
                        + '])) > 0'
                    )
                elif argo_parameters.nullable(port):
                    presence[name] = (
                        'inputs.parameters[' + _json(name) + "] != 'null'"
                    )
                else:
                    presence[name] = True
            bindings = dict(replacements)
            if self.workspace is not None:
                bindings['{{$.workspace_path}}'] = '/kfp-workspace'
            command_expressions = {
                'args': arguments(args or [], bindings, presence)
            }
            if container.command:
                command_expressions['command'] = arguments(
                    container.command, bindings, presence
                )
        if self.workspace is not None:
            declared = {port['name'] for port in inputs['parameters']}
            strings = [
                name
                for name, port in (spec.inputs or {}).items()
                if name in declared
                and structures.spec_type_is_parameter(port.type)
                and _kind(port) == 'String'
            ]
            if workspace_inputs:
                inputs['parameters'].append(
                    {
                        'name': 'kfp-workspace-artifacts',
                        'default': '/kfp-workspace',
                    }
                )
                strings.append('kfp-workspace-artifacts')
            inputs['parameters'].append(
                {'name': 'kfp-workspace-strings', 'default': _json(strings)}
            )
        for key, ports in [('inputs', inputs), ('outputs', outputs)]:
            if any(ports.values()):
                template[key] = {
                    name: values for name, values in ports.items() if values
                }
        self.platform(task, template)
        from kfp.compiler.argo_task_config import project

        project(template, spec, workspace=self.workspace is not None)
        self.bind_configuration(task, template)
        lists = {
            name: {'type': port['type'], 'single': True}
            if port.get('stagedArtifact')
            else port['type']
            for name, port in contract['inputs'].items()
            if port.get('artifactList') or port.get('stagedArtifact')
        }
        if lists:
            from kfp.compiler.argo_artifact_lists import add_staging

            add_staging(
                template,
                lists,
                command_expressions=command_expressions,
                metadata_location=None
                if python
                else {
                    self.driver: {
                        'bucket': self.bucket,
                        'key': self.prefix
                        + '{{workflow.uid}}/{{pod.name}}/kfp-metadata.json',
                    }
                },
            )
        from kfp.compiler.argo_structured import finalize

        finalize(
            template,
            spec,
            container_expressions=None if lists else command_expressions,
        )
        retry = task._task_spec.retry_policy
        if retry:
            count = (
                retry.max_retry_count
                if retry.max_retry_count is not None
                else 0
            )
            if (
                isinstance(count, bool)
                or not isinstance(count, int)
                or count < 0
            ):
                raise ValueError('num_retries must be a non-negative integer.')
            factor = (
                retry.backoff_factor if retry.backoff_factor is not None else 2
            )
            if (
                isinstance(factor, bool)
                or not isinstance(factor, (int, float))
                or factor < 1
                or not float(factor).is_integer()
            ):
                raise ValueError(
                    'Argo requires a positive integer backoff_factor; use e.g. 2 or 2.0, not a fractional factor.'
                )
            template['retryStrategy'] = {
                'limit': str(count),
                # Direct component exits are Failed, not KFP driver errors.
                'retryPolicy': retry.policy or 'Always',
                'backoff': {
                    'duration': f'{structures.convert_duration_to_seconds(retry.backoff_duration or "0s")}s',
                    'factor': str(int(factor)),
                    'maxDuration': f'{structures.convert_duration_to_seconds(retry.backoff_max_duration or "3600s")}s',
                },
            }
        annotations = template.setdefault('metadata', {}).setdefault(
            'annotations', {}
        )
        annotations['pipelines.kubeflow.org/component-type'] = 'RUNTIME'
        for direction, ports in [
            ('input', spec.inputs),
            ('output', spec.outputs),
        ]:
            annotations[
                'pipelines.kubeflow.org/' + direction + '-parameter-types'
            ] = _json(
                {
                    name: argo_parameters.input_kind(port)
                    if direction == 'input'
                    else _kind(port)
                    for name, port in (ports or {}).items()
                    if structures.spec_type_is_parameter(port.type)
                }
            )
        scalar_types = {
            name: _kind(port)
            for name, port in (spec.outputs or {}).items()
            if structures.spec_type_is_parameter(port.type)
        }
        validate_scalars = not python and any(
            kind != 'String' for kind in scalar_types.values()
        )
        if validate_scalars:
            template.setdefault('metadata', {}).setdefault('annotations', {})[
                'pipelines.kubeflow.org/validated-scalars'
            ] = _json(scalar_types)
        # A custom cache key on an enclosing nested-pipeline task scopes every
        # inner task's identity (stock records but ignores it). Pipelines
        # without nested keys keep their existing fingerprints.
        scope = [
            outer._task_spec.cache_key
            for outer in self.nested_tasks
            if outer._task_spec.cache_key
        ]
        if task._task_spec.cache_key:
            # Stock custom keys intentionally override automatic execution/input identity.
            key = hashlib.sha256(
                '\0'.join(
                    [task.component_spec.name, task._task_spec.cache_key]
                    + scope
                ).encode()
            ).hexdigest()
        else:
            # Match stock opt-out caching. Version mutable dependencies or disable
            # caching when their freshness matters; do not reject ordinary pipelines.
            fingerprint = hashlib.sha256(
                _json(
                    {
                        'pipeline': self.pipeline_name,
                        'template': {
                            key: value
                            for key, value in template.items()
                            if key != 'name'
                        },
                        **({'scope': scope} if scope else {}),
                    }
                ).encode()
            ).hexdigest()
            if self.workspace is not None:
                from kfp.compiler.argo_workspace import (
                    NEEDS_WORKSPACE as workspace_used,
                )
            key = (
                "{{=sprig.sha256sum('"
                + fingerprint
                + "'"
                + (' + workflow.uid + node.name' if fresh_pvc else '')
                + (
                    ' + (' + workspace_used + " ? workflow.uid : '')"
                    if self.workspace is not None
                    else ''
                )
                + ' + toJson(inputs.parameters))}}'
            )
        memoize = {
            # Required by the CRD; empty retains unbounded stock caching.
            'maxAge': '',
            'key': key,
            'cache': {'configMap': {'name': self.options.cache_config_map}},
        }
        # Submission-time overrides must also work when compilation disabled caching.
        template.setdefault('metadata', {}).setdefault('annotations', {})[
            'pipelines.kubeflow.org/cache-policy'
        ] = _json({'component': task.component_spec.name, 'memoize': memoize})
        if task._task_spec.enable_caching and not self.disable_caching:
            template['memoize'] = memoize
        if task._task_spec.display_name:
            template.setdefault('metadata', {}).setdefault('annotations', {})[
                'workflows.argoproj.io/display-name'
            ] = task._task_spec.display_name
        if validate_scalars:
            from kfp.compiler.argo_scalars import wrap

            return wrap(self, template, scalar_types)
        return template['name']

    def bind_configuration(self, task, template):
        bindings = self.extra_inputs[id(task)] = []

        def bind(value):
            if isinstance(value, pipeline_channel.PipelineChannel):
                value = str(value)
            if isinstance(value, str):
                for (
                    channel
                ) in pipeline_channel.extract_pipeline_channels_from_string(
                    value
                ):
                    existing = next(
                        (
                            name
                            for name, previous in bindings
                            if previous.pattern == channel.pattern
                        ),
                        None,
                    )
                    name = existing or f'kfp-config-{len(bindings)}'
                    if existing is None:
                        bindings.append((name, channel))
                    value = value.replace(
                        str(channel), _ref('inputs.parameters', name)
                    )
                return value
            if isinstance(value, dict):
                return {bind(key): bind(item) for key, item in value.items()}
            if isinstance(value, list):
                return [bind(item) for item in value]
            return value

        updated = bind(template)
        template.clear()
        template.update(updated)
        if bindings:
            template.setdefault('inputs', {}).setdefault(
                'parameters', []
            ).extend({'name': name} for name, _ in bindings)
        resources = template['container'].get('resources')
        if resources and '{{inputs.parameters.kfp-config-' in _json(resources):
            # Kubernetes quantities are parsed before Argo substitutes container fields.
            patch = json.loads(template.get('podSpecPatch', '{}'))
            containers = patch.setdefault('containers', [])
            main = next(
                (entry for entry in containers if entry['name'] == 'main'), None
            )
            if main is None:
                main = {'name': 'main'}
                containers.append(main)
            main['resources'] = template['container'].pop('resources')
            template['podSpecPatch'] = _json(patch)

    def native_metadata(self, template, contract, outputs):
        """Emit small static metadata as parameters; Argo stages raw
        companions."""
        expressions = {}

        def expression(value):
            marker = f'__kfp_expression_{len(expressions)}__'
            expressions[_json(marker)] = value
            return marker

        producer = {
            'run': expression('workflow.uid'),
            'task': expression('pod.name'),
            'namespace': expression('workflow.namespace'),
        }
        references = []
        for name, port in contract['inputs'].items():
            if 'path' not in port:
                continue
            uri = f'inputs.parameters[{_json("kfp-uri-" + name)}]'
            source = f'fromJSON(inputs.parameters[{_json("kfp-meta-" + name)}])'
            references.append(
                {
                    'port': name,
                    'uri': expression(uri),
                    'producer': expression(source + '.producer'),
                }
            )
        artifacts = []
        for name, port in contract['outputs'].items():
            if 'metadataPath' not in port:
                continue
            uri = (
                "fromJSON(workflow.annotations.json)['"
                + ROOT
                + "'] + '/'"
                + ' + workflow.uid + "/" + pod.name + '
                + _json('/' + name)
            )
            metadata = {
                'schema': SCHEMA,
                'port': name,
                'type': port['type'],
                'producer': producer,
                'uri': expression(uri),
                'metadata': {},
                'inputs': references,
            }
            artifacts.append(metadata)
            companion = next(
                output
                for output in outputs['artifacts']
                if output['name'] == name + '-metadata'
            )
            companion['optional'] = True
            outputs['parameters'].append(
                {'name': 'kfp-meta-' + name, 'value': metadata}
            )
        outputs['parameters'].append(
            {
                'name': 'kfp-metadata',
                'value': {
                    'schema': SCHEMA,
                    'producer': producer,
                    'inputs': references,
                    'artifacts': artifacts,
                    'metrics': {},
                },
            }
        )
        for parameter in outputs['parameters']:
            if not isinstance(parameter.get('value'), dict):
                continue
            value = _json(parameter['value'])
            for marker, replacement in expressions.items():
                value = value.replace(marker, replacement)
            parameter['value'] = '{{=toJson(' + value + ')}}'

    def _kubernetes_config(self, task):
        """The task's kfp-kubernetes settings beneath those of its enclosing
        nested-pipeline tasks.

        Stock records settings on a nested task but never applies them;
        here static ones reach every inner pod, lists accumulate, and
        the inner task wins on conflicting scalars and keys.
        """
        merged = {}
        for outer in self.nested_tasks + [task]:
            ignored = sorted(set(outer.platform_config) - {'kubernetes'})
            if ignored:
                # Stock's Argo backend applies only the kubernetes platform
                # spec and carries the others unexecuted; say so instead of
                # failing the compile.
                warnings.warn(
                    f'Task {outer.name!r} has settings for platforms {ignored}, '
                    'which no Argo backend executes; only kubernetes settings apply.',
                    stacklevel=2,
                )
            config = copy.deepcopy(outer.platform_config.get('kubernetes', {}))
            if outer is not task and _bound_to_parameters(config):
                raise ValueError(
                    f'Kubernetes settings on nested pipeline task {outer.name!r} reference pipeline '
                    'parameters or task outputs, which inner tasks cannot resolve; set them on the inner tasks.'
                )
            _merge_settings(merged, config)
        return merged

    def platform(self, task, template):
        from kfp.compiler import argo_kubernetes

        config = self._kubernetes_config(task)
        container = template['container']
        for source, destination in [
            ('nodeSelector', 'nodeSelector'),
            ('podMetadata', 'metadata'),
            ('tolerations', 'tolerations'),
            ('activeDeadlineSeconds', 'activeDeadlineSeconds'),
        ]:
            if source in config:
                value = config.pop(source)
                if source == 'nodeSelector':
                    if set(value) - {'labels', 'nodeSelectorJson'}:
                        raise ValueError('Unknown node selector setting.')
                    value = (
                        argo_kubernetes.structured(
                            task, value['nodeSelectorJson']
                        )
                        if 'nodeSelectorJson' in value
                        else value.get('labels', {})
                    )
                if source == 'tolerations':
                    value = [
                        argo_kubernetes.structured(task, item['tolerationJson'])
                        if item.get('tolerationJson')
                        else dict(item)
                        for item in value
                    ]
                    for item in value:
                        if 'tolerationSeconds' in item:
                            item['tolerationSeconds'] = int(
                                item['tolerationSeconds']
                            )
                if source == 'activeDeadlineSeconds':
                    value = int(value)
                template[destination] = value
        if 'imagePullPolicy' in config:
            container['imagePullPolicy'] = config.pop('imagePullPolicy')
        for source, kind, field in [
            ('secretAsEnv', 'secretKeyRef', 'secret'),
            ('configMapAsEnv', 'configMapKeyRef', 'configMap'),
        ]:
            for declaration in config.pop(source, []):
                name = argo_kubernetes.parameter(
                    task,
                    declaration.get(field + 'NameParameter', {}),
                    declaration.get(field + 'Name'),
                )
                for entry in declaration['keyToEnv']:
                    container.setdefault('env', []).append(
                        {
                            'name': entry['envVar'],
                            'valueFrom': {
                                kind: {
                                    'name': name,
                                    'key': entry[field + 'Key'],
                                    'optional': declaration.get(
                                        'optional', False
                                    ),
                                }
                            },
                        }
                    )
        for index, mount in enumerate(config.pop('pvcMount', [])):
            parameter = mount.get('pvcNameParameter', {})
            name = parameter.get('runtimeValue', {}).get(
                'constant', mount.get('constant')
            )
            if name is None:
                source = parameter.get(
                    'taskOutputParameter', mount.get('taskOutputParameter', {})
                )
                channel = next(
                    (
                        channel
                        for channel in task.channel_inputs
                        if (
                            source
                            and channel.task_name == source.get('producerTask')
                            and channel.name == source.get('outputParameterKey')
                        )
                        or (
                            not source
                            and channel.full_name
                            == parameter.get(
                                'componentInputParameter',
                                mount.get('componentInputParameter'),
                            )
                        )
                    ),
                    None,
                )
                if channel is None:
                    raise ValueError(
                        'PVC binding does not reference a registered pipeline parameter.'
                    )
                name = str(channel)
            volume = f'kfp-pvc-{index}'
            template.setdefault('volumes', []).append(
                {'name': volume, 'persistentVolumeClaim': {'claimName': name}}
            )
            container.setdefault('volumeMounts', []).append(
                {
                    'name': volume,
                    'mountPath': mount['mountPath'],
                    **(
                        {'subPath': mount['subPath']}
                        if 'subPath' in mount
                        else {}
                    ),
                }
            )
        argo_kubernetes.lower(task, template, config)
        if config:
            raise ValueError(
                f'Kubernetes settings have no native lowering yet: {sorted(config)}. Remove them or add an explicit mapping.'
            )


def compile_argo(
    component, options, pipeline_name, display_name, parameters, kind, schedule
):
    if kind not in {'WorkflowTemplate', 'Workflow', 'CronWorkflow'}:
        raise ValueError(
            'resource_kind must be WorkflowTemplate, Workflow or CronWorkflow.'
        )
    if (kind == 'CronWorkflow') != bool(schedule):
        raise ValueError(
            'Specify schedule only when resource_kind="CronWorkflow".'
        )
    graph = component.component_spec.implementation.graph
    if isinstance(graph, structures.CapturedGraph) and graph.pipeline_root:
        options = copy.copy(options)
        options.artifact_repository = graph.pipeline_root
    builder = _Compiler(options, pipeline_name or component.name)
    if isinstance(graph, structures.CapturedGraph) and graph.config:
        builder.artifact_previews = graph.config.artifact_previews
        builder.workspace = graph.config.workspace
    entrypoint = builder.compile_component(component.component_spec)
    arguments = []
    unknown = set(parameters) - set(component.component_spec.inputs or {})
    if unknown:
        raise ValueError(f'Unknown pipeline parameters: {sorted(unknown)}.')
    for name, port in (component.component_spec.inputs or {}).items():
        if not structures.spec_type_is_parameter(port.type):
            raise ValueError(
                'Root artifact inputs need an explicit native artifact source; pass a produced artifact through a nested DAG.'
            )
        declaration = {'name': name}
        value = parameters.get(name, port.default)
        if value is not None or argo_parameters.nullable(port):
            declaration['value'] = (
                serialize(value, argo_parameters.input_kind(port))
                if kfp.TYPE_CHECK
                else _json(value)
                if argo_parameters.nullable(port)
                else value
                if _kind(port) == 'String' and isinstance(value, str)
                else _json(value)
            )
        if isinstance(declaration.get('value'), str):
            declaration['value'] = builder.value(declaration['value'])
        arguments.append(declaration)
    spec = {
        'entrypoint': entrypoint,
        'serviceAccountName': options.service_account_name,
        'arguments': {'parameters': arguments},
        'templates': builder.templates,
    }
    graph = component.component_spec.implementation.graph
    if isinstance(graph, structures.CapturedGraph):
        if graph.config:
            if graph.config.workspace:
                from kfp.compiler.argo_workspace import configure

                configure(spec, graph.config.workspace)
            for source, destination in [
                ('ttl_seconds_after_finished', 'secondsAfterCompletion'),
                ('ttl_seconds_after_success', 'secondsAfterSuccess'),
                ('ttl_seconds_after_failure', 'secondsAfterFailure'),
            ]:
                value = getattr(graph.config, source)
                if value is not None:
                    spec.setdefault('ttlStrategy', {})[destination] = value
            if graph.config.active_deadline_seconds is not None:
                spec['activeDeadlineSeconds'] = (
                    graph.config.active_deadline_seconds
                )
    name = _name(pipeline_name or component.name)[:48]
    version = hashlib.sha256(_json(spec).encode()).hexdigest()[:12]
    metadata = {
        'labels': {
            'pipelines.kubeflow.org/pipeline': name,
            'pipelines.kubeflow.org/version': version,
        },
        'annotations': {
            'pipelines.kubeflow.org/display-name': display_name
            or (
                graph.display_name
                if isinstance(graph, structures.CapturedGraph)
                else None
            )
            or component.name,
            'pipelines.kubeflow.org/description': component.description or '',
            'pipelines.kubeflow.org/contract': SCHEMA,
            'pipelines.kubeflow.org/storage-state': 'AVAILABLE',
            'pipelines.kubeflow.org/parameter-types': _json(
                {
                    name: argo_parameters.input_kind(port)
                    for name, port in (
                        component.component_spec.inputs or {}
                    ).items()
                    if structures.spec_type_is_parameter(port.type)
                }
            ),
            **builder.root_annotations,
        },
    }
    if kind == 'Workflow':
        metadata['generateName'] = name + '-'
    else:
        metadata['name'] = name + '-' + version
    if kind == 'WorkflowTemplate':
        spec['workflowMetadata'] = {
            'labels': dict(metadata['labels']),
            'annotations': {
                'pipelines.kubeflow.org/storage-state': 'AVAILABLE',
                **builder.root_annotations,
            },
        }
    if kind == 'CronWorkflow':
        spec = {
            'schedules': [schedule],
            'suspend': True,
            'workflowSpec': spec,
            'workflowMetadata': {
                'labels': metadata['labels'],
                'annotations': {
                    'pipelines.kubeflow.org/storage-state': 'AVAILABLE',
                    **builder.root_annotations,
                },
            },
        }
    return {
        'apiVersion': 'argoproj.io/v1alpha1',
        'kind': kind,
        'metadata': metadata,
        'spec': spec,
    }
