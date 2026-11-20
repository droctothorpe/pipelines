# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Project selected native task settings into the public TaskConfig input."""

import copy
import json

from kfp.dsl.component_task_config import TaskConfigField
from kfp.dsl.pipeline_channel import PipelineChannel

RUNTIME_ENV = {
    'KFP_ARGO_RUN_UID',
    'KFP_ARGO_NODE_ID',
    'KFP_ARGO_NAMESPACE',
    'KFP_ARGO_WORKFLOW_NAME',
}


def project(template, component, workspace=False):
    ports = [
        name
        for name, port in (component.inputs or {}).items()
        if port.type == 'TaskConfig'
    ]
    passthroughs = component.task_config_passthroughs or []
    if not ports and not passthroughs:
        return
    container = template['container']
    config = {
        'affinity': None,
        'tolerations': None,
        'nodeSelector': None,
        'env': None,
        'volumes': None,
        'volumeMounts': None,
        'resources': {},
        'resourceClaims': None,
    }
    fields = {
        TaskConfigField.RESOURCES: [(container, 'resources', 'resources')],
        TaskConfigField.ENV: [(container, 'env', 'env')],
        TaskConfigField.KUBERNETES_AFFINITY: [
            (template, 'affinity', 'affinity')
        ],
        TaskConfigField.KUBERNETES_TOLERATIONS: [
            (template, 'tolerations', 'tolerations')
        ],
        TaskConfigField.KUBERNETES_NODE_SELECTOR: [
            (template, 'nodeSelector', 'nodeSelector')
        ],
        TaskConfigField.KUBERNETES_VOLUMES: [
            (template, 'volumes', 'volumes'),
            (container, 'volumeMounts', 'volumeMounts'),
        ],
        TaskConfigField.KUBERNETES_RESOURCE_CLAIMS: [
            (template, 'resourceClaims', 'resourceClaims')
        ],
    }
    for passthrough in {entry.field: entry for entry in passthroughs}.values():
        if passthrough.field not in fields:
            raise ValueError('Unknown TaskConfig passthrough field.')
        if (
            workspace
            and passthrough.field == TaskConfigField.KUBERNETES_VOLUMES
        ):
            if ports and '--argo_input' not in container.get('args', []):
                raise ValueError(
                    'Workspace TaskConfig currently requires a Python component.'
                )
            parameters = template.setdefault('inputs', {}).setdefault(
                'parameters', []
            )
            strings = json.loads(
                next(
                    p['default']
                    for p in parameters
                    if p['name'] == 'kfp-workspace-strings'
                )
            )
            config['__kfp_workspace__'] = {'strings': strings}
            parameters.append(
                {
                    'name': 'kfp-workspace-apply',
                    'default': 'true' if passthrough.apply_to_task else 'false',
                }
            )
        if passthrough.field == TaskConfigField.KUBERNETES_VOLUMES:
            volumes = [
                v
                for v in template.get('volumes', [])
                if {'persistentVolumeClaim', 'secret', 'configMap'} & v.keys()
            ]
            names = {v['name'] for v in volumes}
            mounts = [
                m
                for m in container.get('volumeMounts', [])
                if m['name'] in names
            ]
            config['volumes'] = copy.deepcopy(volumes) or None
            config['volumeMounts'] = copy.deepcopy(mounts) or None
            if not passthrough.apply_to_task:
                template['volumes'] = [
                    v
                    for v in template.get('volumes', [])
                    if v['name'] not in names
                ]
                container['volumeMounts'] = [
                    m
                    for m in container.get('volumeMounts', [])
                    if m['name'] not in names
                ]
            continue
        for source, key, destination in fields[passthrough.field]:
            value = copy.deepcopy(source.get(key, config[destination]))
            if key == 'env':
                value = [
                    entry
                    for entry in value or []
                    if entry['name'] not in RUNTIME_ENV
                ]
            if key == 'resources':
                value.pop('claims', None)
            config[destination] = value
            if not passthrough.apply_to_task:
                if key == 'resourceClaims':
                    container.get('resources', {}).pop('claims', None)
                if key == 'resources' and source.get(key, {}).get('claims'):
                    source[key] = {'claims': source[key]['claims']}
                elif key == 'env':
                    source[key] = [
                        entry
                        for entry in source.get(key, [])
                        if entry['name'] in RUNTIME_ENV
                    ]
                else:
                    source.pop(key, None)

    def channel(value):
        if isinstance(value, PipelineChannel):
            return str(value)
        raise TypeError(f'Unsupported TaskConfig value: {type(value).__name__}')

    if not ports:
        return
    encoded = json.dumps(
        config, sort_keys=True, allow_nan=False, default=channel
    )
    for parameter in template['inputs']['parameters']:
        if parameter['name'] in ports:
            parameter['default'] = encoded
