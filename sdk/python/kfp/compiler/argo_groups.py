# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Argo DAG scopes, conditional branches and parameter fan-out/fan-in."""

import graphlib
import hashlib
import re

from kfp.compiler import argo_continuation
from kfp.compiler.argo_compiler import _json, _ref
from kfp.dsl import for_loop, pipeline_channel, structures, tasks_group
from kfp.dsl.types import type_utils

# Loop items arrive either as JSON text (string list items) or as decoded
# objects (object list items). Argo's expression checker types `item` from the
# concrete value, so `fromJSON(item)` is rejected whenever the item is already an
# object, even in an untaken branch. Serialize first so both shapes decode.
_LOOP_ITEM = "fromJSON(type(item) == 'string' ? item : toJson(item))"


def _expression_reference(reference):
    if reference.startswith('{{='):
        return reference[3:-2]
    reference = reference[2:-2]
    match = re.fullmatch(
        r'tasks\.([^.]+)\.outputs\.(parameters|artifacts)\.(.+)', reference
    )
    if match:
        return f'tasks[{_json(match[1])}].outputs.{match[2]}[{_json(match[3])}]'
    field, name = reference.removeprefix('inputs.').split('.', 1)
    return f'inputs.{field}[{_json(name)}]'


def _parameter_source(reference):
    if reference.startswith('{{inputs.parameters.'):
        return {'expression': _expression_reference(reference)}
    return (
        {'expression': reference[3:-2]}
        if reference.startswith('{{=')
        else {'parameter': reference}
    )


def _artifact_source(reference):
    return (
        {'fromExpression': reference[3:-2]}
        if reference.startswith('{{=')
        else {'from': reference}
    )


def _is_artifact_list(channel):
    # Loop parameters synthesize member channels through __getattr__.
    return (
        isinstance(channel, pipeline_channel.PipelineArtifactChannel)
        and channel.is_artifact_list
    ) or (
        isinstance(channel, for_loop.Collected) and channel.is_artifact_channel
    )


def _nested_artifact_collection(channel, group):
    if (
        not isinstance(channel, for_loop.Collected)
        or not channel.is_artifact_channel
    ):
        return False
    source = channel.output
    if (
        isinstance(source, pipeline_channel.PipelineArtifactChannel)
        and source.is_artifact_list
    ):
        return True
    parent = source.task.parent_task_group if source.task else None
    while parent is not None and not isinstance(
        parent, tasks_group.ParallelFor
    ):
        parent = parent.parent_task_group
    return parent is not None and parent is not group


def _key(channel):
    return (channel.task_name or '', channel.name)


def _port(channel):
    return 'ch-' + hashlib.sha256(repr(_key(channel)).encode()).hexdigest()[:16]


class _Scope:
    def __init__(self, compiler, group, parent=None):
        self.compiler = compiler
        self.group = group
        self.parent = parent
        self.template = {
            'name': compiler._template_name(getattr(group, 'name', 'root')),
            'dag': {'tasks': []},
        }
        compiler.templates.append(self.template)
        self.inputs = {}
        self.exports = {}
        # Group input ports whose producer failure a descendant tolerates; each
        # gets a `kfp-present-<port>` input carrying the producer's status.
        self.presence = set()
        self.tolerant = {}
        self.children = [
            _Scope(compiler, child, self) for child in group.groups
        ]
        self.owners = {task.name: task for task in group.tasks}
        for child in self.children:
            self.owners[child.group.name] = child
            self.owners.update({name: child for name in child.owners})
        self.loop = isinstance(group, tasks_group.ParallelFor)
        self.exit_handler = isinstance(group, tasks_group.ExitHandler)
        self.cleanup = None
        self.wrapper = None
        if self.loop:
            self.wrapper = {
                'name': compiler._template_name(group.name + '-fanout'),
                'dag': {'tasks': []},
            }
            if group.parallelism_limit:
                self.wrapper['parallelism'] = group.parallelism_limit
            compiler.templates.append(self.wrapper)
        elif self.exit_handler:
            # Both are targets: otherwise a successful cleanup masks a failed
            # body because Argo assesses only leaf targets by default.
            self.wrapper = {
                'name': compiler._template_name(group.name + '-exit'),
                'dag': {'failFast': False, 'target': 'body exit', 'tasks': []},
            }
            compiler.templates.append(self.wrapper)

    @property
    def name(self):
        return (self.wrapper or self.template)['name']

    def input(self, channel, field, prefix='', suffix=''):
        if self.loop:
            # String interpolation reconstructs a plain channel; recover its loop identity.
            candidates = [self.group.loop_argument]
            if isinstance(
                self.group.loop_argument, for_loop.LoopParameterArgument
            ):
                candidates.extend(
                    self.group.loop_argument._referenced_subvars.values()
                )
            channel = next(
                (item for item in candidates if _key(item) == _key(channel)),
                channel,
            )
        name = (
            channel.name
            if self.parent is None and not channel.task_name
            else _port(channel)
        )
        if self.loop and isinstance(
            channel,
            (
                for_loop.LoopParameterArgument,
                for_loop.LoopArtifactArgument,
                for_loop.LoopArgumentVariable,
            ),
        ):
            argument = (
                channel.loop_argument
                if isinstance(channel, for_loop.LoopArgumentVariable)
                else channel
            )
            if argument.name == self.group.loop_argument.name:
                self.inputs[_key(channel)] = channel
                name = _port(channel)
        self.inputs[_key(channel)] = channel
        return _ref('inputs.' + field, prefix + name + suffix)

    def resolve(
        self,
        value,
        field='parameters',
        prefix='',
        suffix='',
        collected=False,
        allow_conditional=False,
    ):
        if isinstance(
            value, pipeline_channel.OneOfMixin
        ) and value.task_name == getattr(self.group, 'name', None):
            references = [
                self.resolve(
                    channel, field, prefix, suffix, allow_conditional=True
                )
                for channel in value.channels
            ]
            nullable = self.compiler.nullable_source(value)
            sources = [
                'toJson(' + _expression_reference(ref) + ')'
                if nullable
                and not self.compiler.nullable_source(channel)
                and type_utils.get_parameter_type(channel.channel_type)
                == type_utils.get_parameter_type(str)
                else _expression_reference(ref)
                for ref, channel in zip(references, value.channels)
            ]
            expression = sources[-1]
            for reference, source in reversed(
                list(zip(references[:-1], sources[:-1]))
            ):
                owner = _expression_reference(reference).split('.outputs.', 1)[
                    0
                ]
                expression = (
                    f"({owner}.status == 'Succeeded' ? {source} : {expression})"
                )
            return '{{=' + expression + '}}'
        if isinstance(value, for_loop.Collected):
            if value.is_artifact_channel:
                if field == 'artifacts':
                    raise ValueError(
                        'Collected artifact payloads need list-aware input staging.'
                    )
                prefix = prefix or 'kfp-meta-'
                if (
                    value.output.task_name not in self.owners
                    and self.parent is not None
                ):
                    return self.input(value, field, prefix, suffix)
            return self.resolve(
                value.output, field, prefix, suffix, collected=True
            )
        if not isinstance(value, pipeline_channel.PipelineChannel):
            if isinstance(value, str):
                for (
                    channel
                ) in pipeline_channel.extract_pipeline_channels_from_string(
                    value
                ):
                    value = value.replace(str(channel), self.resolve(channel))
                return self.compiler.workspace_value(value)
            return _json(value)
        if _is_artifact_list(value) and field == 'parameters' and not prefix:
            prefix = 'kfp-meta-'
        owner = self.owners.get(value.task_name)
        if owner is not None:
            if isinstance(owner, _Scope):
                if owner.loop and not collected:
                    raise ValueError(
                        'A loop output used outside its scope must be wrapped in dsl.Collected().'
                    )
                if (
                    isinstance(owner.group, tasks_group._ConditionBase)
                    and not allow_conditional
                ):
                    raise ValueError(
                        'Conditional output escapes its branch; move its consumer inside the branch. Conditional output merges are not yet supported by this prototype.'
                    )
                owner.exports[_key(value)] = (
                    for_loop.Collected(value)
                    if collected
                    and (
                        not owner.loop
                        or isinstance(
                            value, pipeline_channel.PipelineArtifactChannel
                        )
                    )
                    else value
                )
                name = _port(value)
                target = owner.group.name
            else:
                name = value.name
                target = owner.name
            return _ref(
                f'tasks.{target}.outputs.' + field, prefix + name + suffix
            )
        if value.task_name and self.parent is None:
            raise ValueError(
                f'Channel {value.full_name!r} references a task outside the pipeline scope.'
            )
        return self.input(value, field, prefix, suffix)

    def expression(self, value):
        if value is None:
            return 'nil'
        if not isinstance(value, pipeline_channel.PipelineChannel):
            return _json(value)
        reference = _expression_reference(self.resolve(value))
        if self.compiler.nullable_source(
            value
        ) or type_utils.get_parameter_type(
            value.channel_type
        ) != type_utils.get_parameter_type(str):
            reference = 'fromJSON(' + reference + ')'
        return reference

    def conditions(self, group):
        expressions = []
        for condition in group.conditions:
            expression = f'({self.expression(condition.left_operand)} {condition.operator} {self.expression(condition.right_operand)})'
            expressions.append(
                '!' + expression if condition.negate else expression
            )
        return '{{=' + ' && '.join(expressions) + '}}'

    def arguments(self, task, final_status=None):
        arguments = {'parameters': [], 'artifacts': []}
        for name, port in (task.component_spec.inputs or {}).items():
            if name not in task.inputs:
                if (
                    port.type == 'PipelineTaskFinalStatus'
                    and final_status is not None
                ):
                    arguments['parameters'].append(
                        {'name': name, 'value': final_status}
                    )
                    continue
                if port.optional:
                    continue
                if port.type == 'PipelineTaskFinalStatus':
                    raise ValueError(
                        'Task-final-status must be supplied by a native exit hook.'
                    )
                raise ValueError(f'Missing input {name!r} on {task.name!r}.')
            value = task.inputs[name]
            if port.is_artifact_list or self.compiler.staged_source(value):
                arguments['parameters'].extend(
                    {
                        'name': prefix + name,
                        'value': self.resolve(value, prefix=prefix),
                    }
                    for prefix in ('kfp-uri-', 'kfp-meta-')
                )
            elif structures.spec_type_is_parameter(port.type):
                arguments['parameters'].append(
                    {
                        'name': name,
                        'value': self.compiler.argument_value(
                            value, port, task, self.resolve
                        ),
                    }
                )
            else:
                arguments['artifacts'].extend(
                    [
                        {
                            'name': name,
                            'from': self.resolve(value, 'artifacts'),
                        },
                        {
                            'name': name + '-metadata',
                            'from': self.resolve(
                                value, 'artifacts', suffix='-metadata'
                            ),
                            'optional': True,
                        },
                    ]
                )
                for prefix in ('kfp-uri-', 'kfp-meta-'):
                    arguments['parameters'].append(
                        {
                            'name': prefix + name,
                            'value': self.resolve(value, prefix=prefix),
                        }
                    )
        arguments['parameters'].extend(
            {
                'name': name,
                'value': self.compiler.argument_value(
                    channel,
                    structures.InputSpec(type=channel.channel_type),
                    task,
                    self.resolve,
                ),
            }
            for name, channel in self.compiler.extra_inputs.get(id(task), [])
        )
        self.presence.update(argo_continuation.arguments(task, arguments))
        return {key: value for key, value in arguments.items() if value}

    def consumers(self, key):
        """Tasks anywhere in this scope that consume the channel `key`."""
        found = [
            task
            for task in self.group.tasks
            if any(
                isinstance(value, pipeline_channel.PipelineChannel)
                and _key(value) == key
                for value in task.inputs.values()
            )
        ]
        for child in self.children:
            found.extend(child.consumers(key))
        return found

    def thread_presence(self, child, item, arguments):
        """Supply the producer status for each failure-tolerant group input of
        `child`: from the sibling producer's status when it lives here, or from
        this scope's own `kfp-present-` input when it lives further up."""
        for port in sorted(child.presence):
            channel = next(c for c in child.inputs.values() if _port(c) == port)
            if any(
                not task._ignore_upstream_failure_tag
                for task in child.consumers(_key(channel))
            ):
                raise ValueError(
                    f'Output {channel.full_name!r} is consumed inside {child.group.name!r} both with and '
                    'without ignore_upstream_failure(); make every consumer in that group failure-tolerant.'
                )
            artifact = isinstance(
                channel, pipeline_channel.PipelineArtifactChannel
            )
            reference = self.resolve(
                channel, prefix='kfp-uri-' if artifact else ''
            )
            expression = _expression_reference(reference)
            source = re.search(r'tasks\["([^"\\]+)"\]\.outputs\.', expression)
            if source is None:
                self.presence.add(port)
                value = _ref('inputs.parameters', 'kfp-present-' + port)
            else:
                producer = source[1]
                present = f"tasks[{_json(producer)}].status == 'Succeeded'"
                value = '{{=' + present + '}}'
                self.tolerant.setdefault(item['name'], set()).add(producer)
                # Argo refuses to resolve a failed task's outputs, so guard the
                # values; the consumer applies its own fallback.
                for parameter in arguments['parameters']:
                    if parameter['name'] in (
                        port,
                        'kfp-uri-' + port,
                        'kfp-meta-' + port,
                    ):
                        parameter['value'] = (
                            '{{='
                            + present
                            + ' ? ('
                            + _expression_reference(parameter['value'])
                            + " ?? '') : ''}}"
                        )
                for entry in arguments['artifacts']:
                    if entry['name'] in (port, port + '-metadata'):
                        entry['optional'] = True
                        entry['from'] = entry['from'][2:-2]
            arguments['parameters'].append(
                {'name': 'kfp-present-' + port, 'value': value}
            )

    def build(self):
        for child in self.children:
            child.build()
        for task in self.group.tasks:
            target = self.compiler.compile_component(task.component_spec, task)
            item = {
                'name': task.name,
                'template': target,
                'arguments': self.arguments(task),
            }
            if task.dependent_tasks:
                item['dependencies'] = [
                    self.owners[name].group.name
                    if isinstance(self.owners.get(name), _Scope)
                    else name
                    for name in task.dependent_tasks
                ]
            self.template['dag']['tasks'].append(item)
        for child in self.children:
            item = {'name': child.group.name, 'template': child.name}
            if isinstance(child.group, tasks_group._ConditionBase):
                item['when'] = self.conditions(child.group)
            self.template['dag']['tasks'].append(item)
        if self.exit_handler:
            task = self.group.exit_task
            target = self.compiler.compile_component(task.component_spec, task)
            status = (
                "{{=toJson({'state': tasks['body'].status == 'Succeeded' ? 'SUCCEEDED' : 'FAILED', 'pipeline_job_resource_name': workflow.uid, 'pipeline_task_name': "
                + _json(self.group.name)
                + '})}}'
            )
            self.cleanup = {
                'name': 'exit',
                'template': target,
                'depends': 'body.Succeeded || body.Failed || body.Errored',
                'arguments': self.arguments(task, status),
            }

    def propagate(self):
        for channel in list(self.exports.values()):
            self.resolve(channel)
        for child in self.children:
            child.propagate()
            for channel in child.inputs.values():
                if not child.is_loop_item(channel):
                    self.resolve(channel)
            if child.loop:
                self.resolve(
                    child.group.loop_argument.items_or_pipeline_channel
                )
        return (
            len(self.inputs)
            + len(self.exports)
            + sum(child.size() for child in self.children)
        )

    def size(self):
        return (
            len(self.inputs)
            + len(self.exports)
            + sum(child.size() for child in self.children)
        )

    def finish(self):
        # Exports may be discovered by a sibling while lowering its arguments.
        for channel in list(self.exports.values()):
            self.resolve(channel)
        for child in self.children:
            child.finish()
        for child in self.children:
            item = next(
                item
                for item in self.template['dag']['tasks']
                if item['name'] == child.group.name
            )
            arguments = {'parameters': [], 'artifacts': []}
            for channel in child.inputs.values():
                if child.is_loop_item(channel):
                    continue
                name = _port(channel)
                if _is_artifact_list(channel) or self.compiler.staged_source(
                    channel
                ):
                    arguments['parameters'].extend(
                        {
                            'name': prefix + name,
                            'value': self.resolve(channel, prefix=prefix),
                        }
                        for prefix in ('kfp-uri-', 'kfp-meta-')
                    )
                elif isinstance(
                    channel, pipeline_channel.PipelineArtifactChannel
                ):
                    arguments['artifacts'].extend(
                        [
                            {
                                'name': name,
                                'from': self.resolve(channel, 'artifacts'),
                            },
                            {
                                'name': name + '-metadata',
                                'from': self.resolve(
                                    channel, 'artifacts', suffix='-metadata'
                                ),
                                'optional': True,
                            },
                        ]
                    )
                    for prefix in ('kfp-uri-', 'kfp-meta-'):
                        arguments['parameters'].append(
                            {
                                'name': prefix + name,
                                'value': self.resolve(channel, prefix=prefix),
                            }
                        )
                else:
                    arguments['parameters'].append(
                        {'name': name, 'value': self.resolve(channel)}
                    )
            if child.loop:
                arguments['parameters'].append(
                    {
                        'name': 'kfp-items',
                        'value': self.resolve(
                            child.group.loop_argument.items_or_pipeline_channel
                        ),
                    }
                )
            self.thread_presence(child, item, arguments)
            item['arguments'] = {
                key: value for key, value in arguments.items() if value
            }
        parameters, artifacts = [], []
        for channel in self.inputs.values():
            name = (
                channel.name
                if self.parent is None and not channel.task_name
                else _port(channel)
            )
            if _is_artifact_list(channel) or self.compiler.staged_source(
                channel
            ):
                parameters.extend(
                    {'name': prefix + name}
                    for prefix in ('kfp-uri-', 'kfp-meta-')
                )
            elif isinstance(channel, pipeline_channel.PipelineArtifactChannel):
                artifacts.extend(
                    [
                        {'name': name},
                        {'name': name + '-metadata', 'optional': True},
                    ]
                )
                parameters.extend(
                    [{'name': 'kfp-uri-' + name}, {'name': 'kfp-meta-' + name}]
                )
            else:
                parameters.append({'name': name})
        for port in sorted(self.presence):
            parameters.append({'name': 'kfp-present-' + port})
            for artifact in artifacts:
                if artifact['name'] == port:
                    artifact['optional'] = True
        self.template['inputs'] = {
            key: value
            for key, value in [
                ('parameters', parameters),
                ('artifacts', artifacts),
            ]
            if value
        }
        self.output_declarations(
            self.template, lambda channel: self.resolve(channel)
        )
        if self.loop:
            wrapper_inputs = {
                'parameters': [{'name': 'kfp-items'}],
                'artifacts': [],
            }
            arguments = {'parameters': [], 'artifacts': []}
            for channel in self.inputs.values():
                name = _port(channel)
                if self.is_loop_item(channel):
                    if isinstance(channel, for_loop.LoopArtifactArgument):
                        arguments['parameters'].extend(
                            [
                                {
                                    'name': 'kfp-meta-' + name,
                                    'value': '{{item}}',
                                },
                                {
                                    'name': 'kfp-uri-' + name,
                                    'value': '{{=' + _LOOP_ITEM + '.uri}}',
                                },
                            ]
                        )
                        continue
                    item = '{{item}}'
                    if isinstance(channel, for_loop.LoopArgumentVariable):
                        selected = (
                            _LOOP_ITEM + '[' + _json(channel.subvar_name) + ']'
                        )
                        item = (
                            '{{=type('
                            + selected
                            + ") == 'string' ? "
                            + selected
                            + ' : toJson('
                            + selected
                            + ')}}'
                        )
                    arguments['parameters'].append(
                        {'name': name, 'value': item}
                    )
                elif _is_artifact_list(channel) or self.compiler.staged_source(
                    channel
                ):
                    for prefix in ('kfp-uri-', 'kfp-meta-'):
                        wrapper_inputs['parameters'].append(
                            {'name': prefix + name}
                        )
                        arguments['parameters'].append(
                            {
                                'name': prefix + name,
                                'value': _ref(
                                    'inputs.parameters', prefix + name
                                ),
                            }
                        )
                elif isinstance(
                    channel, pipeline_channel.PipelineArtifactChannel
                ):
                    for suffix in ('', '-metadata'):
                        wrapper_inputs['artifacts'].append(
                            {'name': name + suffix, 'optional': bool(suffix)}
                        )
                        arguments['artifacts'].append(
                            {
                                'name': name + suffix,
                                'from': _ref('inputs.artifacts', name + suffix),
                                'optional': bool(suffix),
                            }
                        )
                    for prefix in ('kfp-uri-', 'kfp-meta-'):
                        wrapper_inputs['parameters'].append(
                            {'name': prefix + name}
                        )
                        arguments['parameters'].append(
                            {
                                'name': prefix + name,
                                'value': _ref(
                                    'inputs.parameters', prefix + name
                                ),
                            }
                        )
                else:
                    wrapper_inputs['parameters'].append({'name': name})
                    arguments['parameters'].append(
                        {'name': name, 'value': _ref('inputs.parameters', name)}
                    )
            for port in sorted(self.presence):
                flag = 'kfp-present-' + port
                wrapper_inputs['parameters'].append({'name': flag})
                arguments['parameters'].append(
                    {'name': flag, 'value': _ref('inputs.parameters', flag)}
                )
                for artifact in wrapper_inputs['artifacts']:
                    if artifact['name'] == port:
                        artifact['optional'] = True
                for entry in arguments['artifacts']:
                    if entry['name'] == port:
                        entry['optional'] = True
            self.wrapper['inputs'] = {
                key: value for key, value in wrapper_inputs.items() if value
            }
            self.wrapper['dag']['tasks'] = [
                {
                    'name': 'iteration',
                    'template': self.template['name'],
                    'withParam': '{{inputs.parameters.kfp-items}}',
                    'arguments': {
                        key: value for key, value in arguments.items() if value
                    },
                }
            ]
            self.output_declarations(
                self.wrapper,
                lambda channel: _ref(
                    'tasks.iteration.outputs.parameters', _port(channel)
                ),
            )
        if self.exit_handler:
            self.wrapper['inputs'] = self.template['inputs']
            arguments = {'parameters': [], 'artifacts': []}
            for field, ports in self.template['inputs'].items():
                for port in ports:
                    arguments[field].append(
                        {
                            'name': port['name'],
                            'value' if field == 'parameters' else 'from': _ref(
                                'inputs.' + field, port['name']
                            ),
                            **(
                                {'optional': True}
                                if port.get('optional')
                                else {}
                            ),
                        }
                    )
            self.wrapper['dag']['tasks'] = [
                {
                    'name': 'body',
                    'template': self.template['name'],
                    'arguments': {
                        key: value for key, value in arguments.items() if value
                    },
                },
                self.cleanup,
            ]
            self.output_declarations(
                self.wrapper,
                lambda channel: _ref(
                    'tasks.body.outputs.parameters', _port(channel)
                ),
            )
        dependencies = {}
        for item in self.template['dag']['tasks']:
            references = re.findall(
                r'tasks\.([a-zA-Z0-9_-]+)\.', _json(item)
            ) + re.findall(r'tasks\[\\?"([^"\\]+)\\?"\]', _json(item))
            deps = set(item.get('dependencies', [])) | set(references)
            deps.discard(item['name'])
            if deps:
                item['dependencies'] = sorted(deps)
            dependencies[item['name']] = deps
        argo_continuation.dependencies(
            self.template['dag'],
            {
                task.name: task
                for task in self.group.tasks
                if task._ignore_upstream_failure_tag
            },
            self.tolerant,
        )
        missing = (
            set().union(*dependencies.values()) - set(dependencies)
            if dependencies
            else set()
        )
        if missing:
            raise ValueError(
                f'Dependency crosses a group boundary: {sorted(missing)}.'
            )
        try:
            tuple(graphlib.TopologicalSorter(dependencies).static_order())
        except graphlib.CycleError as error:
            raise ValueError(
                'Pipeline contains a cyclic dependency.'
            ) from error

    def is_loop_item(self, channel):
        if not self.loop:
            return False
        if isinstance(channel, for_loop.LoopArgumentVariable):
            channel = channel.loop_argument
        return (
            isinstance(
                channel,
                (for_loop.LoopParameterArgument, for_loop.LoopArtifactArgument),
            )
            and channel.name == self.group.loop_argument.name
        )

    def output_declarations(self, template, reference):
        parameters, artifacts = [], []
        for channel in self.exports.values():
            name = _port(channel)
            if _is_artifact_list(channel) or self.compiler.staged_source(
                channel
            ):
                for prefix in ('kfp-uri-', 'kfp-meta-'):
                    if self.loop and template is self.wrapper:
                        source = _ref(
                            'tasks.iteration.outputs.parameters', prefix + name
                        )
                    elif self.exit_handler and template is self.wrapper:
                        source = _ref(
                            'tasks.body.outputs.parameters', prefix + name
                        )
                    else:
                        source = self.resolve(channel, prefix=prefix)
                    source_spec = {'parameter': source}
                    if self.loop and template is self.wrapper:
                        if _nested_artifact_collection(channel, self.group):
                            source_spec = {
                                'expression': 'toJson(flatten(map(fromJSON('
                                + _expression_reference(source)
                                + "), {type(#) == 'string' ? fromJSON(#) : #})))"
                            }
                        source_spec['default'] = '[]'
                    parameters.append(
                        {'name': prefix + name, 'valueFrom': source_spec}
                    )
            elif isinstance(channel, pipeline_channel.PipelineArtifactChannel):
                if self.loop:
                    raise ValueError(
                        'Argo does not aggregate output artifacts; use a supported parameter collection.'
                    )
                wrapped = self.exit_handler and template is self.wrapper
                source = (
                    _ref('tasks.body.outputs.artifacts', name)
                    if wrapped
                    else self.resolve(channel, 'artifacts')
                )
                artifacts.append({'name': name, **_artifact_source(source)})
                metadata_source = (
                    _ref('tasks.body.outputs.artifacts', name + '-metadata')
                    if wrapped
                    else self.resolve(channel, 'artifacts', suffix='-metadata')
                )
                artifacts.append(
                    {
                        'name': name + '-metadata',
                        **_artifact_source(metadata_source),
                        'optional': True,
                    }
                )
                for prefix in ('kfp-uri-', 'kfp-meta-'):
                    source = (
                        _ref('tasks.body.outputs.parameters', prefix + name)
                        if wrapped
                        else self.resolve(channel, prefix=prefix)
                    )
                    parameters.append(
                        {
                            'name': prefix + name,
                            'valueFrom': _parameter_source(source),
                        }
                    )
            else:
                parameters.append(
                    {
                        'name': name,
                        'valueFrom': {
                            **_parameter_source(reference(channel)),
                            **(
                                {'default': '[]'}
                                if self.loop and template is self.wrapper
                                else {}
                            ),
                        },
                    }
                )
        if parameters or artifacts:
            template['outputs'] = {
                key: value
                for key, value in [
                    ('parameters', parameters),
                    ('artifacts', artifacts),
                ]
                if value
            }


def compile_graph(compiler, component_spec, graph):
    scope = _Scope(compiler, graph.pipeline.groups[0])
    scope.build()
    outputs = graph.outputs
    if outputs is not None:
        outputs = (
            outputs._asdict()
            if hasattr(outputs, '_asdict')
            else outputs
            if isinstance(outputs, dict)
            else {'Output': outputs}
        )
        for channel in outputs.values():
            scope.resolve(channel)
    previous = -1
    for _ in range(len(compiler.templates) + 1):
        size = scope.propagate()
        if size == previous:
            break
        previous = size
    scope.finish()
    # Root parameters must keep declarations even if unused, including defaults.
    ports = {'parameters': [], 'artifacts': []}
    for name, port in (component_spec.inputs or {}).items():
        compiler.input_port(
            ports, name, port, staged=name in compiler.staged_graph_inputs
        )
    scope.template['inputs'] = {
        key: value for key, value in ports.items() if value
    }
    if outputs:
        parameters, artifacts = [], []
        for name, channel in outputs.items():
            if structures.spec_type_is_parameter(
                component_spec.outputs[name].type
            ):
                parameters.append(
                    {
                        'name': name,
                        'valueFrom': _parameter_source(scope.resolve(channel)),
                    }
                )
                continue
            for prefix in ('kfp-uri-', 'kfp-meta-'):
                parameters.append(
                    {
                        'name': prefix + name,
                        'valueFrom': {
                            'parameter': scope.resolve(channel, prefix=prefix)
                        },
                    }
                )
            if not _is_artifact_list(channel) and not compiler.staged_source(
                channel
            ):
                for suffix in ('', '-metadata'):
                    artifacts.append(
                        {
                            'name': name + suffix,
                            'from': scope.resolve(
                                channel, 'artifacts', suffix=suffix
                            ),
                            **({'optional': True} if suffix else {}),
                        }
                    )
        scope.template['outputs'] = {
            key: value
            for key, value in [
                ('parameters', parameters),
                ('artifacts', artifacts),
            ]
            if value
        }
    return scope.name
