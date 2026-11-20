# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Nullable parameter wire values preserve None, empty strings and literal null."""

import re

from kfp.compiler.argo_structured import expression as literal_expression
from kfp.dsl import for_loop, pipeline_channel, structures
from kfp.dsl.argo_runtime import serialize


def nullable(port):
    return (
        structures.spec_type_is_parameter(port.type)
        and port.optional
        and port.default is None
        and port.type not in ('TaskConfig', 'PipelineTaskFinalStatus')
    )


def input_kind(port, allow_nullable=True):
    from kfp.compiler.argo_compiler import _kind

    return ('Nullable' if allow_nullable and nullable(port) else '') + _kind(
        port
    )


def output_mapping(graph):
    outputs = graph.outputs
    if outputs is None:
        return {}
    if hasattr(outputs, '_asdict'):
        return outputs._asdict()
    return outputs if isinstance(outputs, dict) else {'Output': outputs}


def source_nullable(channel, component, graph, seen=None):
    if isinstance(channel, pipeline_channel.OneOfMixin):
        return any(
            source_nullable(item, component, graph, seen)
            for item in channel.channels
        )
    if isinstance(channel, for_loop.Collected) or not isinstance(
        channel, pipeline_channel.PipelineParameterChannel
    ):
        return False
    if not channel.task_name:
        port = (component.inputs or {}).get(channel.name) if component else None
        return port is not None and nullable(port)
    task = graph.pipeline.tasks.get(channel.task_name) if graph else None
    if task is None:
        return False
    inner = task.component_spec.implementation.graph
    if not isinstance(inner, structures.CapturedGraph):
        return False
    seen = set() if seen is None else set(seen)
    key = (id(task), channel.name)
    if key in seen:
        raise ValueError('Cyclic nullable output reference.')
    seen.add(key)
    output = output_mapping(inner).get(channel.name)
    return source_nullable(output, task.component_spec, inner, seen)


def bind(value, port, resolver, is_nullable, allow_nullable=True):
    from kfp.compiler.argo_compiler import _kind
    from kfp.compiler.argo_groups import _expression_reference

    target_nullable = allow_nullable and nullable(port)
    kind = _kind(port)
    if isinstance(value, pipeline_channel.PipelineChannel):
        source = resolver(value)
        origin_nullable = is_nullable(value)
        if target_nullable:
            if kind == 'String' and not origin_nullable:
                return '{{=toJson(' + _expression_reference(source) + ')}}'
            return source
        if origin_nullable:
            decoded = 'fromJSON(' + _expression_reference(source) + ')'
            if port.optional and port.default is not None:
                decoded = (
                    '('
                    + decoded
                    + ' ?? '
                    + literal_expression(port.default)
                    + ')'
                )
            else:
                decoded = (
                    '('
                    + _expression_reference(source)
                    + " == 'null' ? asInt('Required parameter cannot be None') : "
                    + decoded
                    + ')'
                )
            return (
                '{{='
                + (decoded if kind == 'String' else 'toJson(' + decoded + ')')
                + '}}'
            )
        return source
    if isinstance(value, str):
        channels = {
            str(c): c
            for c in pipeline_channel.extract_pipeline_channels_from_string(
                value
            )
        }
        if channels:
            parts, offset = [], 0
            for match in re.finditer(
                '|'.join(re.escape(token) for token in channels), value
            ):
                if match.start() > offset:
                    parts.append(
                        literal_expression(
                            resolver(value[offset : match.start()])
                        )
                    )
                channel = channels[match[0]]
                reference = _expression_reference(resolver(channel))
                if is_nullable(channel):
                    reference = (
                        '('
                        + reference
                        + " == 'null' ? asInt('Cannot interpolate None') : string(fromJSON("
                        + reference
                        + ')))'
                    )
                parts.append(reference)
                offset = match.end()
            if offset < len(value):
                parts.append(literal_expression(resolver(value[offset:])))
            expression = ' + '.join(parts)
            if target_nullable:
                expression = 'toJson(' + expression + ')'
            return '{{=' + expression + '}}'
        value = resolver(value)
    return serialize(value, input_kind(port, allow_nullable))
