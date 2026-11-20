# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Kubernetes modifiers lowered to native pod fields."""

import copy
import json

from kfp.compiler.argo_structured import CLAIM_REFS, CLAIMS, MARKER
from kfp.dsl.types import type_utils


def parameter(task, declaration, legacy=None, require_string=True):
    runtime = declaration.get('runtimeValue', {})
    if 'constant' in runtime:
        return runtime['constant']
    if not declaration:
        return legacy
    source = declaration.get('taskOutputParameter', {})
    channel = next(
        (
            c
            for c in task.channel_inputs
            if (
                source
                and c.task_name == source.get('producerTask')
                and c.name == source.get('outputParameterKey')
            )
            or (
                not source
                and c.full_name == declaration.get('componentInputParameter')
            )
        ),
        None,
    )
    if channel is None:
        raise ValueError(
            'Kubernetes binding does not reference a registered pipeline parameter.'
        )
    if require_string and type_utils.get_parameter_type(
        channel.channel_type
    ) != type_utils.get_parameter_type(str):
        raise ValueError(
            'Kubernetes resource names require a string parameter.'
        )
    return str(channel)


def structured(task, declaration):
    if 'constant' not in declaration.get('runtimeValue', {}):
        return {MARKER: parameter(task, declaration, require_string=False)}
    value = parameter(task, declaration)
    value = json.loads(value) if isinstance(value, str) else value
    if not isinstance(value, dict):
        raise ValueError('Kubernetes configuration must be a JSON object.')
    return value


def lower(task, template, config):
    container = template['container']

    def volume(name, definition, mount, read_only=False):
        declaration = {'name': name, **definition}
        existing = next(
            (v for v in template.get('volumes', []) if v['name'] == name), None
        )
        if existing is not None and existing != declaration:
            raise ValueError(f'Conflicting Kubernetes volume {name!r}.')
        if existing is None:
            template.setdefault('volumes', []).append(declaration)
        container.setdefault('volumeMounts', []).append(
            {
                'name': name,
                'mountPath': mount,
                **({'readOnly': True} if read_only else {}),
            }
        )

    for source, driver, field in [
        ('secretAsVolume', 'secret', 'secret'),
        ('configMapAsVolume', 'configMap', 'configMap'),
    ]:
        for index, value in enumerate(config.pop(source, [])):
            name = parameter(
                task,
                value.get(field + 'NameParameter', {}),
                value.get(field + 'Name'),
            )
            volume(
                f'kfp-{driver.lower()}-{index}',
                {
                    driver: {
                        'secretName' if driver == 'secret' else 'name': name,
                        'optional': value.get('optional', False),
                    }
                },
                value['mountPath'],
                True,
            )
    pull_secrets = config.pop('imagePullSecret', [])
    if pull_secrets:
        patch = json.loads(template.get('podSpecPatch', '{}'))
        patch['imagePullSecrets'] = [
            {
                'name': parameter(
                    task,
                    value.get('secretNameParameter', {}),
                    value.get('secretName'),
                )
            }
            for value in pull_secrets
        ]
        template['podSpecPatch'] = json.dumps(patch)
    for value in config.pop('fieldPathAsEnv', []):
        container.setdefault('env', []).append(
            {
                'name': value['name'],
                'valueFrom': {'fieldRef': {'fieldPath': value['fieldPath']}},
            }
        )
    for value in config.pop('emptyDirMounts', []):
        volume(
            value['volumeName'],
            {
                'emptyDir': {
                    key: value[key]
                    for key in ('medium', 'sizeLimit')
                    if key in value
                }
            },
            value['mountPath'],
        )
    shared = config.pop('enabledSharedMemory', None)
    if shared:
        volume(
            shared['volumeName'],
            {
                'emptyDir': {
                    'medium': 'Memory',
                    **(
                        {'sizeLimit': shared['size']}
                        if shared.get('size')
                        else {}
                    ),
                }
            },
            '/dev/shm',
        )
    for value in config.pop('genericEphemeralVolume', []):
        claim = {
            'accessModes': value['accessModes'],
            'resources': {'requests': {'storage': value['size']}},
        }
        if not value.get('defaultStorageClass'):
            claim['storageClassName'] = value.get('storageClassName', '')
        volume(
            value['volumeName'],
            {
                'ephemeral': {
                    'volumeClaimTemplate': {
                        'metadata': value.get('metadata', {}),
                        'spec': claim,
                    }
                }
            },
            value['mountPath'],
        )
    context = config.pop('securityContext', None)
    if context is not None:
        if set(context) - {'runAsUser', 'runAsGroup', 'runAsNonRoot'}:
            raise ValueError('Unsupported Kubernetes security context field.')
        context = copy.deepcopy(context)
        for name in ('runAsUser', 'runAsGroup'):
            if name in context:
                context[name] = int(context[name])
        container['securityContext'] = {
            **context,
            'allowPrivilegeEscalation': False,
            'capabilities': {'drop': ['ALL']},
            'seccompProfile': {'type': 'RuntimeDefault'},
        }
    for value in config.pop('initContainers', []):
        if value['name'] in (
            'init',
            'wait',
            'main',
            'kfp-launcher',
            'kfp-stage-artifacts',
        ):
            raise ValueError(
                'Init container name is reserved for native execution.'
            )
        entry = {
            key: copy.deepcopy(value[key])
            for key in (
                'name',
                'image',
                'command',
                'args',
                'env',
                'restartPolicy',
                'resources',
            )
            if key in value
        }
        if value.get('volumeMounts'):
            entry['volumeMounts'] = [
                {'name': m['volumeName'], 'mountPath': m['mountPath']}
                for m in value['volumeMounts']
            ]
        if any(
            c['name'] == entry['name']
            for c in template.get('initContainers', [])
        ):
            raise ValueError('Init container names must be unique.')
        template.setdefault('initContainers', []).append(entry)
    node_affinities = config.pop('nodeAffinity', [])
    for value in node_affinities:
        if not any(
            value.get(key)
            for key in ('nodeAffinityJson', 'matchExpressions', 'matchFields')
        ):
            continue
        target = template.setdefault('affinity', {}).setdefault(
            'nodeAffinity', {}
        )
        if value.get('nodeAffinityJson'):
            node = structured(task, value['nodeAffinityJson'])
            if MARKER in node:
                if len(node_affinities) != 1:
                    raise ValueError(
                        'Mixed dynamic node affinity terms need merged structured lowering.'
                    )
                template['affinity']['nodeAffinity'] = node
                continue
            for key, item in node.items():
                if key == 'requiredDuringSchedulingIgnoredDuringExecution':
                    target.setdefault(key, {}).setdefault(
                        'nodeSelectorTerms', []
                    ).extend(item.get('nodeSelectorTerms', []))
                elif key == 'preferredDuringSchedulingIgnoredDuringExecution':
                    target.setdefault(key, []).extend(item)
                else:
                    raise ValueError('Unknown node affinity field.')
        else:
            term = {
                key: copy.deepcopy(value[key])
                for key in ('matchExpressions', 'matchFields')
                if key in value
            }
            if 'weight' in value:
                target.setdefault(
                    'preferredDuringSchedulingIgnoredDuringExecution', []
                ).append({'weight': value['weight'], 'preference': term})
            else:
                target.setdefault(
                    'requiredDuringSchedulingIgnoredDuringExecution', {}
                ).setdefault('nodeSelectorTerms', []).append(term)
    resource_claims = config.pop('podResourceClaims', [])
    for value in resource_claims:
        if 'resourceClaimJson' in value:
            declaration = value['resourceClaimJson']
            if 'constant' not in declaration.get('runtimeValue', {}):
                if len(resource_claims) != 1:
                    raise ValueError(
                        'Mixed dynamic resource claim declarations need merged structured lowering.'
                    )
                binding = parameter(task, declaration, require_string=False)
                template['resourceClaims'] = {CLAIMS: binding}
                container.setdefault('resources', {})['claims'] = {
                    CLAIM_REFS: binding
                }
                continue
            claims = parameter(task, declaration)
            if claims is None:
                continue
            claims = claims if isinstance(claims, list) else [claims]
        else:
            claims = [
                {
                    'resourceClaimTemplateName': value.get(
                        'resourceClaimTemplateName'
                    )
                }
            ]
        for claim in claims:
            name = claim.get('resourceClaimTemplateName')
            if not isinstance(name, str) or not name:
                raise ValueError(
                    'Resource claims require a non-empty resourceClaimTemplateName.'
                )
            if any(
                c['name'] == name for c in template.get('resourceClaims', [])
            ):
                raise ValueError('Duplicate resource claim name.')
            template.setdefault('resourceClaims', []).append(
                {**claim, 'name': name}
            )
            container.setdefault('resources', {}).setdefault(
                'claims', []
            ).append({'name': name})
    for value in config.pop('podAffinity', []):
        target = template.setdefault('affinity', {}).setdefault(
            'podAntiAffinity' if value.get('anti') else 'podAffinity', {}
        )
        term = {'topologyKey': value['topologyKey']}
        for prefix, destination in [
            ('Pod', 'labelSelector'),
            ('Namespace', 'namespaceSelector'),
        ]:
            selector = {}
            for suffix, key in [
                ('Expressions', 'matchExpressions'),
                ('Labels', 'matchLabels'),
            ]:
                source = 'match' + prefix + suffix
                if source in value:
                    selector[key] = value[source]
            if selector:
                term[destination] = selector
        if value.get('namespaces'):
            term['namespaces'] = value['namespaces']
        if 'weight' in value:
            target.setdefault(
                'preferredDuringSchedulingIgnoredDuringExecution', []
            ).append({'weight': value['weight'], 'podAffinityTerm': term})
        else:
            target.setdefault(
                'requiredDuringSchedulingIgnoredDuringExecution', []
            ).append(term)
