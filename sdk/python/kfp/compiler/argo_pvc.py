# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""The user-requested PVC task runs its Kubernetes operation in its own pod.

No per-component driver or controller is introduced. This source is
embedded in CreatePVC/DeletePVC containers so they do not require a
fork-specific image.
"""

import json
import sys
from pathlib import Path
from uuid import uuid4

from kubernetes import client, config


def execute(operation, parameters, namespace, api=None):
    if api is None:
        config.load_incluster_config()
        api = client.CoreV1Api()
    if operation == 'delete':
        name = parameters['pvc_name']
        try:
            claim = api.read_namespaced_persistent_volume_claim(name, namespace)
            api.delete_namespaced_persistent_volume_claim(
                name,
                namespace,
                body=client.V1DeleteOptions(
                    preconditions=client.V1Preconditions(uid=claim.metadata.uid)
                ),
            )
        except client.ApiException as error:
            if error.status != 404:
                raise
        return name
    if operation != 'create':
        raise ValueError(f'Unknown PVC operation: {operation}')
    name, suffix = parameters.get('pvc_name'), parameters.get('pvc_name_suffix')
    if name and suffix:
        raise ValueError(
            'At most one of pvc_name and pvc_name_suffix can be non-empty.'
        )
    name = name or str(uuid4()) + (suffix or '')
    manifest = {
        'apiVersion': 'v1',
        'kind': 'PersistentVolumeClaim',
        'metadata': {'name': name, 'namespace': namespace},
        'spec': {
            'accessModes': parameters['access_modes'],
            'resources': {'requests': {'storage': parameters['size']}},
        },
    }
    for key, field in [
        ('storage_class_name', 'storageClassName'),
        ('volume_name', 'volumeName'),
        ('data_source', 'dataSource'),
    ]:
        if parameters.get(key) is not None:
            manifest['spec'][field] = parameters[key]
    if parameters.get('annotations') is not None:
        manifest['metadata']['annotations'] = parameters['annotations']
    try:
        api.create_namespaced_persistent_volume_claim(namespace, manifest)
    except client.ApiException as error:
        # Stock CreatePVC reuses an existing name without modifying that claim.
        if error.status != 409:
            raise
    return name


def decode(raw, encoded):
    """Return the task parameters, JSON-decoding only the names the compiler
    encoded: lists, dictionaries and nullable inputs (`null` becomes None).
    Required strings, such as DeletePVC's name bound from an upstream output,
    arrive raw and are never parsed."""
    parameters = {item['name']: item['value'] for item in json.loads(raw)}
    for key in json.loads(encoded):
        if key in parameters:
            parameters[key] = json.loads(parameters[key])
    return parameters


if __name__ == '__main__':
    operation, raw, namespace, encoded = sys.argv[1:5]
    parameters = decode(raw, encoded)
    name = execute(operation, parameters, namespace)
    if operation == 'create':
        Path(sys.argv[5]).write_text(name)
    print(f'{operation} PVC {name}')
