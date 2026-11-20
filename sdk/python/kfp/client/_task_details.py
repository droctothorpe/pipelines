# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Project native execution snapshots into public task response models."""

import base64
import gzip
import io as streams
import json
import re
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

TRANSIENT_MESSAGES = {'PodInitializing', 'ContainerCreating'}
SUCCESS_PHASES = {'Succeeded', 'Skipped', 'Omitted'}
TERMINAL_STATES = {'SUCCEEDED', 'FAILED', 'SKIPPED', 'CACHED'}
USER_EXIT = 'Error (exit code '


def _reason(message):
    return message.split(':', 1)[0].strip()


def _split_container_prefix(message):
    """Argo may prefix the container name, as in "main: OOMKilled (exit code
    137)".

    Only a single-word prefix counts, so a message body is never taken
    as a reason.
    """
    prefix, separator, rest = message.partition(':')
    if separator and not re.search(r'\s', prefix.strip()):
        return True, rest.strip()
    return False, ''


def _match_category(message):
    lower = message.lower()
    reason = _reason(message).lower()
    # image-pull is checked before runtime: ErrImagePull messages contain "error".
    if reason in ('errimagepull', 'imagepullbackoff') or any(
        phrase in lower
        for phrase in ('back-off pulling image', 'failed to pull image')
    ):
        return 'image-pull'
    if (
        any(phrase in lower for phrase in ('is forbidden', 'admission webhook'))
        or reason == 'forbidden'
        or any(token in reason for token in ('kyverno', 'podsecurity'))
    ):
        return 'admission'
    if any(
        marker in lower
        for marker in (
            'unschedulable',
            'failedscheduling',
            'insufficient cpu',
            'insufficient memory',
        )
    ):
        return 'scheduling'
    if reason == 'error' or any(
        reason == code or reason.startswith(code + ' ')
        for code in ('oomkilled', 'crashloopbackoff')
    ):
        return 'runtime'
    return 'unknown'


def lifecycle_category(message):
    """Stock's pod failure classification of a lifecycle message.

    Returns image-pull, scheduling, runtime, admission or unknown, and None when
    the message is empty. A user-script exit ("Error (exit code N)") stays
    unknown: that is a user failure, not an infrastructure one.
    """
    message = (message or '').strip()
    if not message:
        return None
    has_prefix, rest = _split_container_prefix(message)
    if message.startswith(USER_EXIT) or (
        has_prefix and rest.startswith(USER_EXIT)
    ):
        return 'unknown'
    category = _match_category(message)
    if category == 'unknown' and has_prefix:
        category = _match_category(rest)
    return category


def lifecycle_message(message, phase):
    """Stock drops transient startup reasons, messages of successful nodes and
    user-code exits from lifecycle_message; the raw text stays in status
    metadata."""
    if not message:
        return None
    if message in TRANSIENT_MESSAGES or _reason(message) in TRANSIENT_MESSAGES:
        return None
    if phase in SUCCESS_PHASES:
        return None
    has_prefix, rest = _split_container_prefix(message)
    if message.startswith(USER_EXIT) or (
        has_prefix and rest.startswith(USER_EXIT)
    ):
        return None
    return message


def task_history(node, state):
    """Argo keeps only start and finish times, so the history is the transition
    into RUNNING and the terminal state.

    Cached and skipped tasks never ran.
    """
    started, finished = node.get('startedAt'), node.get('finishedAt')
    history = []
    if started and state not in ('CACHED', 'SKIPPED'):
        history.append(
            models.PipelineTaskTaskStatus(
                update_time=timestamp(started), state='RUNNING'
            )
        )
    if state in TERMINAL_STATES and (finished or started):
        history.append(
            models.PipelineTaskTaskStatus(
                update_time=timestamp(finished or started), state=state
            )
        )
    return history


def iteration_index(node):
    match = re.search(r'\((\d+):', node.get('displayName') or '')
    return match[1] if match else None


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


def io(node, template, direction, workflow_name=None, pod_times=None):
    data = node.get(direction, {})
    # Outputs were created when this task finished; inputs were created when
    # their producer finished, known for producers in the same workflow.
    finished = timestamp(node.get('finishedAt') or node.get('startedAt'))
    pod_times = pod_times or {}
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
                            created_at=finished
                            if direction == 'outputs'
                            else pod_times.get(producer['task']),
                        )
                    )
                port = name.removeprefix('kfp-meta-')
                # Inputs name the task that produced them; the identity records
                # the producing pod, which is that task's pod name here.
                producers = {
                    identity['producer']['task'] for identity in identities
                }
                artifacts.append(
                    models.InputOutputsIOArtifact(
                        artifact_key=port,
                        artifacts=entries,
                        type='OUTPUT'
                        if direction == 'outputs'
                        else 'COLLECTED_INPUTS'
                        if ports.get(port, {}).get('artifactList')
                        else 'TASK_OUTPUT_INPUT',
                        producer=models.V2IOProducer(
                            task_name=next(iter(producers))
                        )
                        if direction != 'outputs' and len(producers) == 1
                        else None,
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


def pod_name(resource, pod, root):
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
    return name


def tasks(resource, pod_uids=None):
    nodes = node_status(resource)
    pod_uids = pod_uids or {}
    if nodes is None:
        return None
    status = resource.get('status', {})
    spec = status.get('storedWorkflowTemplateSpec') or resource.get('spec', {})
    templates = {t['name']: t for t in spec.get('templates', [])}
    root = resource['metadata']['name']
    pod_times = {
        pod_name(resource, node, root): timestamp(
            node.get('finishedAt') or node.get('startedAt')
        )
        for node in nodes.values()
        if node['type'] == 'Pod'
        and not node.get('memoizationStatus', {}).get('hit')
    }
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
            name = pod_name(resource, pod, root)
            pods.append(
                models.PipelineTaskTaskPod(
                    name=name, uid=pod_uids.get(name), type='EXECUTOR'
                )
            )
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
        state = (
            'CACHED'
            if cached
            else phases.get(node.get('phase'), 'RUNTIME_STATE_UNSPECIFIED')
        )
        lifecycle = lifecycle_message(message, node.get('phase'))
        parent = parents.get(key)
        while parent in owners:
            parent = owners[parent]
        path, cursor = [], key
        while (
            cursor
            and cursor != root
            and nodes.get(cursor, {}).get('name') != root
        ):
            path.append(nodes[cursor].get('displayName', cursor))
            cursor = parents.get(cursor)
            while cursor in owners:
                cursor = owners[cursor]
        attributes = None
        if node['type'] == 'TaskGroup':
            attributes = models.PipelineTaskTypeAttributes(
                iteration_count=str(len(node.get('children', [])))
            )
        elif nodes.get(parent, {}).get('type') == 'TaskGroup':
            index = iteration_index(node)
            if index is None:
                siblings = nodes[parent].get('children', [])
                index = str(siblings.index(key)) if key in siblings else None
            if index is not None:
                attributes = models.PipelineTaskTypeAttributes(
                    iteration_index=index
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
                state=state,
                state_history=task_history(node, state),
                type=kind,
                type_attributes=attributes,
                parent_task_id=parent,
                scope_path='.'.join(['root'] + path[::-1]),
                lifecycle_message=lifecycle,
                lifecycle_category=lifecycle_category(lifecycle),
                status_metadata=models.PipelineTaskStatusMetadata(
                    message=message
                )
                if message
                else None,
                child_tasks=child_tasks[key],
                inputs=io(node, template, 'inputs', root, pod_times),
                outputs=io(node, template, 'outputs', root, pod_times),
            )
        )
    return result
