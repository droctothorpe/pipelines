# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Preserve structured runtime values through Argo's string parameter
boundary."""

import json
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class _Expression:
    source: str


MARKER = '__kfp_native_json__'
CLAIMS = '__kfp_native_claims__'
CLAIM_REFS = '__kfp_native_claim_refs__'
MERGE = '__kfp_native_merge__'
# A dynamic value that may be one object or a list of them (stock's
# toleration JSON accepted either); spread into the surrounding list.
SPREAD = '__kfp_native_spread__'
MARKERS = {MARKER, CLAIMS, CLAIM_REFS, MERGE, SPREAD}
REFERENCE = re.compile(
    r'\{\{(inputs\.parameters\.[^{}]+|workflow\.annotations\.[^{}]+|workflow\.(?:name|uid|namespace)|pod\.name)\}\}'
)


def deferred(value):
    return (
        isinstance(value, dict)
        and len(value) == 1
        and next(iter(value)) in MARKERS
    )


def contains(value):
    if isinstance(value, _Expression):
        return True
    if isinstance(value, dict):
        return deferred(value) or any(contains(v) for v in value.values())
    if isinstance(value, list):
        return any(contains(v) for v in value)
    return False


def literal(value):
    # Delimiters in user strings must not close the surrounding Argo expression.
    return (
        json.dumps(value, allow_nan=False)
        .replace('{', r'\u007b')
        .replace('}', r'\u007d')
    )


def reference(value):
    if value.startswith('inputs.parameters.'):
        return (
            'inputs.parameters['
            + literal(value.removeprefix('inputs.parameters.'))
            + ']'
        )
    if value.startswith('workflow.annotations.'):
        return (
            'fromJSON(workflow.annotations.json)['
            + literal(value.removeprefix('workflow.annotations.'))
            + ']'
        )
    return value


def _merge(spec):
    """Static entries first, then each dynamic JSON value's entries, as stock's
    driver appends them at run time; a null value contributes nothing."""
    parts = [expression(spec['static'])]
    for binding in spec['dynamic']:
        match = REFERENCE.fullmatch(binding)
        if match is None:
            raise ValueError('Structured setting lacks a bound native input.')
        decoded = 'fromJSON(' + reference(match[1]) + ')'
        if spec.get('items'):
            parts.append(
                '('
                + decoded
                + ' == nil ? [] : '
                + expression({spec['items']: binding})
                + ')'
            )
        else:
            parts.append(
                '('
                + decoded
                + ''.join('?.' + key for key in spec['path'])
                + ' ?? [])'
            )
    merged = 'concat(' + ', '.join(parts) + ')'
    if spec.get('wrap'):
        # Kubernetes rejects an empty required term list; omit the field then.
        return (
            'len('
            + merged
            + ') > 0 ? sprig.dict('
            + literal(spec['wrap'])
            + ', '
            + merged
            + ') : nil'
        )
    return merged


def expression(value):
    if isinstance(value, _Expression):
        return value.source
    if isinstance(value, dict):
        if deferred(value):
            marker = next(iter(value))
            if marker == MERGE:
                return _merge(value[marker])
            match = REFERENCE.fullmatch(value[marker])
            if match is None:
                raise ValueError(
                    'Structured setting lacks a bound native input.'
                )
            decoded = 'fromJSON(' + reference(match[1]) + ')'
            if marker == MARKER:
                return decoded
            if marker == SPREAD:
                return (
                    '(sprig.kindIs("slice", '
                    + decoded
                    + ') ? '
                    + decoded
                    + ' : ['
                    + decoded
                    + '])'
                )
            items = (
                '(sprig.kindIs("slice", '
                + decoded
                + ') ? '
                + decoded
                + ' : ['
                + decoded
                + '])'
            )
            body = 'sprig.dict("name", #.resourceClaimTemplateName)'
            if marker == CLAIMS:
                body = 'sprig.mergeOverwrite(sprig.dict(), #, ' + body + ')'
            return 'map(' + items + ', {' + body + '})'
        return (
            'sprig.dict('
            + ','.join(
                part
                for key, entry in value.items()
                for part in (literal(key), expression(entry))
            )
            + ')'
        )
    if isinstance(value, list):
        if any(deferred(v) and next(iter(v)) == SPREAD for v in value):
            parts, literal_run = [], []
            for item in value:
                if deferred(item) and next(iter(item)) == SPREAD:
                    if literal_run:
                        parts.append('[' + ','.join(literal_run) + ']')
                        literal_run = []
                    parts.append(expression(item))
                else:
                    literal_run.append(expression(item))
            if literal_run:
                parts.append('[' + ','.join(literal_run) + ']')
            return 'concat(' + ', '.join(parts) + ')'
        return '[' + ','.join(expression(v) for v in value) + ']'
    if value is None:
        return 'nil'
    if not isinstance(value, str):
        return json.dumps(value, allow_nan=False)
    parts, offset = [], 0
    for match in REFERENCE.finditer(value):
        if match.start() > offset:
            parts.append(literal(value[offset : match.start()]))
        parts.append('string(' + reference(match[1]) + ')')
        offset = match.end()
    if offset < len(value) or not parts:
        parts.append(literal(value[offset:]))
    return ' + '.join(parts)


def finalize(template, component, container_expressions=None):
    patch = json.loads(template.get('podSpecPatch', '{}'))
    if container_expressions:
        main = next(
            (c for c in patch.get('containers', []) if c['name'] == 'main'),
            None,
        )
        if main is None:
            main = {'name': 'main'}
            patch.setdefault('containers', []).append(main)
        main.update(
            {
                name: _Expression(source)
                for name, source in container_expressions.items()
            }
        )
    for key in ('nodeSelector', 'affinity', 'tolerations', 'resourceClaims'):
        if contains(template.get(key)):
            patch[key] = template.pop(key)
    if contains(patch):
        template['podSpecPatch'] = '{{=toJson(' + expression(patch) + ')}}'
    names = {
        name
        for name, port in (component.inputs or {}).items()
        if port.type == 'TaskConfig'
    }
    for parameter in template.get('inputs', {}).get('parameters', []):
        if parameter['name'] not in names:
            continue
        value = json.loads(parameter['default'])
        if contains(value):
            if '--argo_input' not in template.get('container', {}).get(
                'args', []
            ):
                raise ValueError(
                    'Dynamic structured TaskConfig currently requires a Python component.'
                )

            def bind_names(item):
                if isinstance(item, dict):
                    if deferred(item):
                        marker = next(iter(item))
                        if marker == MERGE:
                            raise ValueError(
                                'Merged static and dynamic settings cannot pass through TaskConfig.'
                            )
                        match = REFERENCE.fullmatch(item[marker])
                        if match is None or not match[1].startswith(
                            'inputs.parameters.'
                        ):
                            raise ValueError(
                                'TaskConfig setting lacks a bound native input.'
                            )
                        return {
                            marker: match[1].removeprefix('inputs.parameters.')
                        }
                    return {
                        key: bind_names(entry) for key, entry in item.items()
                    }
                if isinstance(item, list):
                    return [bind_names(entry) for entry in item]
                return item

            parameter['default'] = json.dumps(
                bind_names(value), allow_nan=False
            )
