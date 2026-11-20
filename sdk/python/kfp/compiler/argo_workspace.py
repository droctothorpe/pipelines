# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Run-scoped shared workspaces using native PVC templates and pod patches."""

import copy

PATH = '/kfp-workspace'
PLACEHOLDER = '{{$.workspace_path}}'
NAME = 'kfp-workspace'
NEEDS_WORKSPACE = "any(fromJSON(inputs.parameters['kfp-workspace-strings']), {sprig.contains('/kfp-workspace', inputs.parameters[#])})"
USES_WORKSPACE = (
    NEEDS_WORKSPACE
    + " && (inputs.parameters['kfp-workspace-apply'] ?? 'true') == 'true'"
)


def configure(spec, workspace):
    claim = copy.deepcopy(
        workspace.get_workspace().get('kubernetes', {}).get('pvcSpecPatch', {})
    )
    modes = claim.get('accessModes')
    if (
        not isinstance(modes, list)
        or not modes
        or not all(
            mode
            in (
                'ReadWriteOnce',
                'ReadOnlyMany',
                'ReadWriteMany',
                'ReadWriteOncePod',
            )
            for mode in modes
        )
    ):
        raise ValueError(
            'Workspace PVC accessModes must be supplied in pvcSpecPatch; deployment-provided workspace defaults are not yet bound.'
        )
    if claim.get('storageClassName') == '':
        raise ValueError(
            'Workspace storageClassName must be omitted or non-empty.'
        )
    if workspace.size.startswith('-'):
        raise ValueError('Workspace size must not be negative.')
    claim['resources'] = claim.get('resources') or {}
    claim['resources']['requests'] = claim['resources'].get('requests') or {}
    claim['resources']['requests']['storage'] = workspace.size
    for template in spec['templates']:
        for volume in template.get('volumes', []):
            if volume['name'] == NAME:
                raise ValueError(
                    'Workspace volume name conflicts with a user volume.'
                )
        for mount in template.get('container', {}).get('volumeMounts', []):
            if mount['name'] == NAME or mount['mountPath'].startswith(PATH):
                raise ValueError(
                    'Workspace path conflicts with a user volume mount.'
                )
    spec['volumeClaimTemplates'] = [{'metadata': {'name': NAME}, 'spec': claim}]
    # Workflow and template pod patches are applied separately by Argo, preserving
    # dynamic resource/staging patches and avoiding mounts on unrelated tasks.
    patch = "sprig.dict('volumes', [sprig.dict('name', 'kfp-workspace', 'persistentVolumeClaim', sprig.dict('claimName', workflow.name + '-kfp-workspace'))], 'containers', [sprig.dict('name', 'main', 'volumeMounts', [sprig.dict('name', 'kfp-workspace', 'mountPath', '/kfp-workspace')])])"
    spec['podSpecPatch'] = (
        '{{=toJson(' + USES_WORKSPACE + ' ? ' + patch + ' : sprig.dict())}}'
    )
