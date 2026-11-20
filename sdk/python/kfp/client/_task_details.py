# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Project native execution snapshots into public task response models."""

import base64
import gzip
import io as streams
import json
from collections import defaultdict
from datetime import datetime

from kfp import server_api as models
from kfp.dsl.argo_runtime import (
    deserialize,
    deserialize_collection,
    resolve_task_config,
)
from kfp.dsl.argo_staging import records

PREFIX = 'pipelines.kubeflow.org/'
MAX_NODE_STATUS_BYTES = 64 * 1024 * 1024


def timestamp(value):
    return (
        datetime.fromisoformat(value.replace('Z', '+00:00')) if value else None
    )


def contract(template):
    args = template.get('container', {}).get('args', [])
    if '--argo_input' not in args:
        return {}
    try:
        return json.loads(args[args.index('--argo_input') + 1])
    except (ValueError, IndexError, TypeError):
        return {}


def io(node, template, direction, workflow_name=None):
    data = node.get(direction, {})
    annotations = template.get('metadata', {}).get('annotations', {})
    kinds = json.loads(
        annotations.get(
            PREFIX
            + ('input' if direction == 'inputs' else 'output')
            + '-parameter-types',
            '{}',
        )
    )
    ports = contract(template).get(direction, {})
    kinds = {
        **{
            name: port['type']
            for name, port in ports.items()
            if not port.get('artifactList') and 'metadataPath' not in port
        },
        **kinds,
    }
    parameters, artifacts = [], []
    values = {
        entry['name']: entry.get('value')
        for entry in data.get('parameters', [])
    }
    for parameter in data.get('parameters', []):
        name = parameter['name']
        if 'value' not in parameter:
            continue
        value = parameter['value']
        if name.startswith('kfp-meta-'):
            try:
                identities = records(value)
                entries = []
                for identity in identities:
                    producer = identity['producer']
                    title = (
                        identity['type'].split('@')[0].removeprefix('system.')
                    )
                    title = {
                        'Metrics': 'Metric',
                        'ClassificationMetrics': 'ClassificationMetric',
                        'SlicedClassificationMetrics': 'SlicedClassificationMetric',
                    }.get(title, title)
                    if (
                        title
                        not in models.ArtifactArtifactType.allowable_values
                    ):
                        title = 'TYPE_UNSPECIFIED'
                    entries.append(
                        models.V2Artifact(
                            artifact_id='/'.join(
                                [
                                    producer['run'],
                                    producer['task'],
                                    identity['port'],
                                ]
                            ),
                            name=identity['port'],
                            type=title,
                            uri=identity['uri'],
                            metadata=identity.get('metadata'),
                            namespace=producer['namespace'],
                        )
                    )
                port = name.removeprefix('kfp-meta-')
                artifacts.append(
                    models.InputOutputsIOArtifact(
                        artifact_key=port,
                        artifacts=entries,
                        type='OUTPUT'
                        if direction == 'outputs'
                        else 'COLLECTED_INPUTS'
                        if ports.get(port, {}).get('artifactList')
                        else 'TASK_OUTPUT_INPUT',
                    )
                )
            except (ValueError, KeyError, TypeError):
                # Native workflows may use these names without the KFP metadata contract.
                continue
        elif name.startswith(
            ('kfp-uri-', 'kfp-config-', 'kfp-present-', 'kfp-workspace-')
        ) or name in (
            'kfp-metadata',
            'kfp-run-id',
            'kfp-node-name',
            'kfp-namespace',
            'kfp-items',
        ):
            continue
        else:
            port = ports.get(name, {})
            if values.get(port.get('presenceParameter')) == 'false':
                continue
            kind = kinds.get(name, 'String')
            try:
                value = (
                    deserialize_collection(
                        value,
                        port['collectionElementType'],
                        port['collectionDepth'],
                    )
                    if 'collectionElementType' in port
                    else deserialize(value, kind)
                )
                if port.get('taskConfig'):
                    value = resolve_task_config(value, values, workflow_name)
            except (ValueError, TypeError, KeyError):
                # A failed task can expose an invalid raw output; retain the evidence.
                pass
            parameters.append(
                models.InputOutputsIOParameter(
                    parameter_key=name,
                    value=value,
                    type='OUTPUT' if direction == 'outputs' else 'UNSPECIFIED',
                )
            )
    return models.PipelineTaskInputOutputs(
        parameters=parameters, artifacts=artifacts
    )


def node_status(resource):
    """Read ordinary/default-gzip node status without an Argo auth bridge."""
    status = resource.get('status', {})
    nodes = status.get('nodes')
    if isinstance(nodes, dict) and nodes:
        return nodes
    if status.get('compressedNodes'):
        encoded = status['compressedNodes']
        if len(encoded) > MAX_NODE_STATUS_BYTES * 2:
            raise ValueError(
                'Compressed workflow node status exceeds the SDK size limit.'
            )
        compressed = base64.b64decode(encoded, validate=True)
        if not compressed.startswith(b'\x1f\x8b'):
            # Alternative Argo codecs need server hydration, like SQL offload.
            return None
        with gzip.GzipFile(fileobj=streams.BytesIO(compressed)) as source:
            content = source.read(MAX_NODE_STATUS_BYTES + 1)
        if len(content) > MAX_NODE_STATUS_BYTES:
            raise ValueError(
                'Expanded workflow node status exceeds the SDK size limit.'
            )
        nodes = json.loads(content)
        if not isinstance(nodes, dict):
            raise ValueError('Workflow node status must be an object.')
        return nodes
    if status.get('offloadNodeStatusVersion'):
        return None
    return nodes if isinstance(nodes, dict) else None


def tasks(resource):
    nodes = node_status(resource)
    if nodes is None:
        return None
    status = resource.get('status', {})
    spec = status.get('storedWorkflowTemplateSpec') or resource.get('spec', {})
    templates = {t['name']: t for t in spec.get('templates', [])}
    root = resource['metadata']['name']
    parents = {key: node.get('boundaryID') for key, node in nodes.items()}
    for key, node in nodes.items():
        if node['type'] in ('Retry', 'TaskGroup', 'StepGroup'):
            for child in node.get('children', []):
                parents[child] = key
    opaque = {
        key
        for key, node in nodes.items()
        if node['type'] == 'Retry'
        or templates.get(node.get('templateName'), {})
        .get('metadata', {})
        .get('annotations', {})
        .get(PREFIX + 'component-wrapper')
        == 'true'
        or templates.get(node.get('templateName'), {})
        .get('metadata', {})
        .get('annotations', {})
        .get(PREFIX + 'component-type')
        == 'IMPORTER'
    }
    owners = {}
    for key in nodes:
        parent = parents.get(key)
        seen = set()
        while parent and parent not in seen:
            seen.add(parent)
            if parent in opaque:
                # A retry can contain a validation wrapper; all of its internal
                # nodes belong to the outer logical task, including real pods.
                owners[key] = parent
            parent = parents.get(parent)
    visible = {key: node for key, node in nodes.items() if key not in owners}
    owned_children = defaultdict(list)
    child_tasks = defaultdict(list)
    for child, owner in owners.items():
        owned_children[owner].append(nodes[child])
    for child, entry in visible.items():
        child_tasks[parents.get(child)].append(
            models.PipelineTaskChildTask(
                task_id=child, name=entry.get('displayName', child)
            )
        )
    result = []
    phases = {
        'Running': 'RUNNING',
        'Succeeded': 'SUCCEEDED',
        'Failed': 'FAILED',
        'Error': 'FAILED',
        'Skipped': 'SKIPPED',
        'Omitted': 'SKIPPED',
    }
    for key, node in visible.items():
        template = templates.get(node.get('templateName'), {})
        cached = bool(node.get('memoizationStatus', {}).get('hit'))
        children = owned_children[key]
        message = node.get('message') or next(
            (
                n.get('message')
                for n in children
                if n.get('phase') in ('Failed', 'Error') and n.get('message')
            ),
            None,
        )
        pod_nodes = (
            (
                [node]
                if node['type'] == 'Pod'
                else [n for n in children if n['type'] == 'Pod']
            )
            if not cached
            else []
        )
        pods = []
        for pod in pod_nodes:
            if pod.get('memoizationStatus', {}).get('hit'):
                continue
            name = pod.get('podName')
            if not name and pod.get('name') == root:
                name = root
            if (
                not name
                and resource['metadata']
                .get('annotations', {})
                .get('workflows.argoproj.io/pod-name-format')
                == 'v1'
            ):
                name = pod['id']
            if not name and pod.get('templateName'):
                name = (
                    root
                    + '-'
                    + pod['templateName']
                    + '-'
                    + pod['id'].rsplit('-', 1)[-1]
                )
            pods.append(models.PipelineTaskTaskPod(name=name, type='EXECUTOR'))
        kind = (
            template.get('metadata', {})
            .get('annotations', {})
            .get(PREFIX + 'component-type')
        )
        kind = (
            'ROOT'
            if key == root or node.get('name') == root
            else kind
            or (
                'RUNTIME'
                if node['type'] in ('Pod', 'Retry') or key in opaque
                else 'LOOP'
                if node['type'] == 'TaskGroup'
                else 'DAG'
            )
        )
        result.append(
            models.V2PipelineTask(
                name=node.get('name', key),
                display_name=node.get('displayName', key),
                task_id=key,
                run_id=resource['metadata']['uid'],
                pods=pods,
                cache_fingerprint=node.get('memoizationStatus', {}).get('key'),
                create_time=timestamp(node.get('startedAt')),
                end_time=timestamp(node.get('finishedAt')),
                state='CACHED'
                if cached
                else phases.get(node.get('phase'), 'RUNTIME_STATE_UNSPECIFIED'),
                type=kind,
                parent_task_id=parents.get(key),
                lifecycle_message=message,
                status_metadata=models.PipelineTaskStatusMetadata(
                    message=message
                )
                if message
                else None,
                child_tasks=child_tasks[key],
                inputs=io(node, template, 'inputs', root),
                outputs=io(node, template, 'outputs', root),
            )
        )
    return result
