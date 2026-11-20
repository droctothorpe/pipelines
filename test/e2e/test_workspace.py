# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Shared workspace: conditional mounts and run-scoped cache identity."""

import pytest
from kfp import dsl

from e2e import support


@dsl.component
def write_workspace(workspace: str, message: str) -> str:
    from pathlib import Path

    path = Path(workspace) / 'shared.txt'
    path.write_text(message)
    return str(path)


@dsl.component
def read_workspace(path: str, expected: str) -> str:
    from pathlib import Path

    actual = Path(path).read_text()
    assert actual == expected
    return actual


@dsl.component
def unrelated(message: str = 'ordinary', payload: dict = None) -> str:
    from pathlib import Path

    assert not Path('/kfp-workspace').exists()
    assert payload == {'path': '/kfp-workspace'}
    return message


@dsl.component
def no_inputs() -> str:
    from pathlib import Path

    assert not Path('/kfp-workspace').exists()
    return 'no workspace requested'


@dsl.component(
    task_config_passthroughs=[
        dsl.TaskConfigPassthrough(dsl.TaskConfigField.KUBERNETES_VOLUMES)
    ]
)
def external_workspace(
    workspace: str, expected: bool, config: dsl.TaskConfig
) -> str:
    import os
    from pathlib import Path

    assert not Path('/kfp-workspace').exists(), (
        'apply_to_task=False must keep the PVC off this pod'
    )
    if expected:
        assert config.volumes == [
            {
                'name': 'kfp-workspace',
                'persistentVolumeClaim': {
                    'claimName': os.environ['KFP_ARGO_WORKFLOW_NAME']
                    + '-kfp-workspace'
                },
            }
        ], config
        assert config.volume_mounts == [
            {'name': 'kfp-workspace', 'mountPath': '/kfp-workspace'}
        ], config
    else:
        assert not config.volumes and not config.volume_mounts, config
    return 'workspace context verified'


@dsl.pipeline(
    name='shared-workspace-compatibility',
    pipeline_config=dsl.PipelineConfig(
        workspace=dsl.WorkspaceConfig(
            size='1Mi',
            kubernetes=dsl.KubernetesWorkspaceConfig(
                pvcSpecPatch={
                    'accessModes': ['ReadWriteOnce'],
                    'storageClassName': 'standard',
                }
            ),
        )
    ),
)
def pipeline(message: str = 'shared workspace'):
    written = write_workspace(
        workspace=dsl.WORKSPACE_PATH_PLACEHOLDER, message=message
    )
    read_workspace(path=written.output, expected=message)
    unrelated(payload={'path': '/kfp-workspace'})
    no_inputs()
    external_workspace(workspace=dsl.WORKSPACE_PATH_PLACEHOLDER, expected=True)
    external_workspace(workspace='ordinary', expected=False)


@pytest.mark.full
def test_workspace_mounts_and_cache_identity(client, record):
    for index in range(2):
        submitted, done = support.run_pipeline(client, pipeline, timeout=300)
        raw = support.workflow(client, done)
        assert done.state == 'SUCCEEDED', support.phases(raw)
        for name in ('write-workspace', 'read-workspace', 'external-workspace'):
            assert (
                not support.node(raw, name)
                .get('memoizationStatus', {})
                .get('hit')
            ), name
        if index:
            for name in ('unrelated', 'no-inputs', 'external-workspace-2'):
                assert (
                    support.node(raw, name)
                    .get('memoizationStatus', {})
                    .get('hit')
                ), name
        pods = support.pods(client, raw)
        mounted = [
            p
            for p in pods
            if any(v['name'] == 'kfp-workspace' for v in p['spec']['volumes'])
        ]
        assert len(mounted) == 2, [
            (p['metadata']['name'], p['spec']['volumes']) for p in pods
        ]
        assert all(
            next(
                v for v in p['spec']['volumes'] if v['name'] == 'kfp-workspace'
            )['persistentVolumeClaim']['claimName']
            == raw['metadata']['name'] + '-kfp-workspace'
            for p in mounted
        )
        record(
            run_id=submitted.run_id,
            iteration=index,
            pods=len(pods),
            workspace_pods=len(mounted),
        )
