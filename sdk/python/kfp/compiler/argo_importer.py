# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Import external artifact references using native DAG outputs, without a pod."""

import hashlib
import re
from urllib.parse import urlsplit

from kfp.compiler.argo_compiler import _json, _kind
from kfp.dsl.argo_runtime import SCHEMA

PLACEHOLDER = re.compile(r"\{\{\$.inputs.parameters\['([^']+)'\]\}\}")


def compile_importer(compiler, task):
    spec = task.component_spec
    importer = spec.implementation.importer
    if importer.download_to_workspace:
        raise ValueError(
            'Importer workspace downloads require workspace volume lowering.'
        )
    literal = task.inputs.get('uri')
    if isinstance(literal, str) and urlsplit(literal).scheme not in (
        's3',
        'gs',
        'http',
        'https',
    ):
        raise ValueError(
            'Native importers support s3://, gs://, http:// and https:// artifact URIs.'
        )
    name = compiler._template_name(task.name)
    template = {
        'name': name,
        'metadata': {
            'annotations': {'pipelines.kubeflow.org/component-type': 'IMPORTER'}
        },
    }
    compiler.templates.append(template)
    resolver = compiler._template_name(task.name + '-resolve')
    # Argo DAGs need a child; a zero-duration control node does not create a pod.
    compiler.templates.append({'name': resolver, 'suspend': {'duration': '0s'}})

    def expression(value):
        if isinstance(value, dict):
            pairs = [
                part
                for key, item in value.items()
                for part in (
                    'string(' + expression(key) + ')',
                    expression(item),
                )
            ]
            return 'sprig.dict(' + ','.join(pairs) + ')'
        if isinstance(value, list):
            return '[' + ','.join(expression(item) for item in value) + ']'
        if value is None:
            return 'nil'
        if not isinstance(value, str):
            return _json(value)
        match = PLACEHOLDER.fullmatch(value)
        if match:
            parameter = 'inputs.parameters[' + _json(match[1]) + ']'
            return (
                parameter
                if _kind(spec.inputs[match[1]]) == 'String'
                else 'fromJSON(' + parameter + ')'
            )
        pieces, offset = [], 0
        for match in PLACEHOLDER.finditer(value):
            pieces.extend(
                [
                    _json(value[offset : match.start()]),
                    'inputs.parameters[' + _json(match[1]) + ']',
                ]
            )
            offset = match.end()
        pieces.append(_json(value[offset:]))
        return ' + '.join(pieces)

    uri = "inputs.parameters['uri']"
    producer = "{run: inputs.parameters['kfp-run-id'], task: inputs.parameters['kfp-node-name'], namespace: inputs.parameters['kfp-namespace']}"
    metadata = (
        '{schema:'
        + _json(SCHEMA)
        + ',port:"artifact",type:'
        + _json(importer.schema_title)
        + ',producer:'
        + producer
        + ',uri:'
        + uri
        + ',metadata:'
        + expression(importer.metadata or {})
        + ',inputs:[]}'
    )
    # Importers have no metadata file in object storage; their raw companion
    # must also travel with collected identities for list consumers.
    identity = metadata
    summary = (
        '{schema:'
        + _json(SCHEMA)
        + ',producer:'
        + producer
        + ',inputs:[],artifacts:['
        + metadata
        + '],metrics:{}}'
    )
    inputs = {'parameters': [], 'artifacts': []}
    for key, port in spec.inputs.items():
        compiler.input_port(inputs, key, port)
    inputs['parameters'].extend(
        [
            {'name': 'kfp-run-id', 'default': '{{workflow.uid}}'},
            {'name': 'kfp-node-name', 'default': '{{node.name}}'},
            {'name': 'kfp-namespace', 'default': '{{workflow.namespace}}'},
        ]
    )
    for driver in ('http', 's3', 'gcs'):
        location = (
            {'url': '{{inputs.parameters.uri}}'}
            if driver == 'http'
            else {
                'bucket': '{{=sprig.urlParse(' + uri + ').host}}',
                'key': "{{=sprig.trimPrefix('/', sprig.urlParse("
                + uri
                + ').path)}}',
            }
        )
        inputs['artifacts'].append({'name': driver, driver: location})
    inputs['artifacts'].append(
        {'name': 'metadata', 'raw': {'data': '{{=toJson(' + metadata + ')}}'}}
    )
    choice = (
        "sprig.hasPrefix('s3://', "
        + uri
        + ") ? inputs.artifacts.s3 : (sprig.hasPrefix('gs://', "
        + uri
        + ') ? inputs.artifacts.gcs : inputs.artifacts.http)'
    )
    template.update(
        inputs=inputs,
        dag={'tasks': [{'name': 'resolve', 'template': resolver}]},
        outputs={
            'artifacts': [
                {'name': 'artifact', 'fromExpression': choice},
                {
                    'name': 'artifact-metadata',
                    'from': '{{inputs.artifacts.metadata}}',
                },
            ],
            'parameters': [
                {'name': 'kfp-uri-artifact', 'valueFrom': {'expression': uri}},
                {
                    'name': 'kfp-meta-artifact',
                    'valueFrom': {'expression': 'toJson(' + identity + ')'},
                },
                {
                    'name': 'kfp-metadata',
                    'valueFrom': {'expression': 'toJson(' + summary + ')'},
                },
            ],
        },
    )
    if not importer.reimport:
        fingerprint = hashlib.sha256(
            _json(
                {
                    'type': importer.schema_title,
                    'metadata': importer.metadata,
                    'identityVersion': 2,
                }
            ).encode()
        ).hexdigest()
        cache_inputs = (
            '['
            + ','.join(
                'inputs.parameters[' + _json(key) + ']' for key in spec.inputs
            )
            + ']'
        )
        template['memoize'] = {
            'maxAge': '',
            'key': "{{=sprig.sha256sum('importer-"
            + fingerprint
            + "' + toJson("
            + cache_inputs
            + '))}}',
            'cache': {'configMap': {'name': compiler.options.cache_config_map}},
        }
    return name
