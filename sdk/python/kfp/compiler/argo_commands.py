# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Lower runtime IfPresent/Concat argv to native expression arrays."""

import json
import re

from kfp.compiler.argo_structured import expression, literal


def arguments(values, bindings, presence):
    """Return an expression for argv, preserving branch-dependent argument count."""
    pattern = (
        re.compile(
            '|'.join(
                re.escape(key)
                for key in sorted(bindings, key=len, reverse=True)
            )
        )
        if bindings
        else None
    )

    def quoted(value):
        if '{{$.' in value or '{{$}}' in value:
            raise ValueError('Unbound KFP placeholder in container arguments.')
        return literal(value)

    def text(value):
        value = (
            value
            if isinstance(value, str)
            else json.dumps(value, allow_nan=False)
        )
        parts, offset = [], 0
        for match in pattern.finditer(value) if pattern else []:
            if match.start() > offset:
                parts.append(quoted(value[offset : match.start()]))
            replacement = bindings[match[0]]
            native = (
                replacement[3:-2]
                if replacement.startswith('{{=') and replacement.endswith('}}')
                else expression(replacement)
            )
            parts.append('string(' + native + ')')
            offset = match.end()
        if offset < len(value) or not parts:
            parts.append(quoted(value[offset:]))
        return '(' + ' + '.join(parts) + ')'

    def elements(value):
        if isinstance(value, str) and value.lstrip().startswith(
            ('{"IfPresent":', '{"Concat":')
        ):
            value = json.loads(value)
        if isinstance(value, list):
            return (
                'flatten([' + ','.join(elements(item) for item in value) + '])'
                if value
                else '[]'
            )
        if isinstance(value, dict) and 'IfPresent' in value:
            clause = value['IfPresent']
            condition = presence.get(clause['InputName'], False)
            if isinstance(condition, bool):
                return elements(clause.get('Then' if condition else 'Else', []))
            return (
                '('
                + condition
                + ' ? '
                + elements(clause.get('Then', []))
                + ' : '
                + elements(clause.get('Else', []))
                + ')'
            )
        if isinstance(value, dict) and 'Concat' in value:
            return '[sprig.join("", ' + elements(value['Concat']) + ')]'
        if value is None:
            return '[]'
        return '[' + text(value) + ']'

    return elements(values)
