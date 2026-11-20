# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Native shared workspace, conditional mounts, and run-scoped cache identity."""

import json
import os
from uuid import uuid4

import kfp
from kfp import dsl


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


if __name__ == '__main__':
    namespace = os.environ.get('KFP_TEST_NAMESPACE', 'kfp-argo')
    client = kfp.Client(
        host=os.environ.get('KFP_TEST_HOST', 'http://127.0.0.1:3003'),
        namespace=namespace,
        existing_token=os.environ['KFP_TEST_TOKEN'],
    )
    report = []
    for index in range(2):
        run = client.create_run_from_pipeline_func(
            pipeline,
            arguments={},
            run_name='Workspace compatibility ' + uuid4().hex[:8],
            experiment_name='SDK backwards compatibility',
            namespace=namespace,
        )
        done = run.wait_for_run_completion(timeout=240)
        raw = client._run_api.transport.request(
            'GET',
            f'/argo/api/v1/workflows/{namespace}/{done.pipeline_spec["metadata"]["name"]}',
        )
        nodes = list(raw['status']['nodes'].values())
        assert done.state == 'SUCCEEDED', [
            (n.get('displayName'), n.get('phase'), n.get('message'))
            for n in nodes
        ]
        for name in ('write-workspace', 'read-workspace', 'external-workspace'):
            task = next(n for n in nodes if n.get('displayName') == name)
            assert not task.get('memoizationStatus', {}).get('hit'), task
        if index:
            for name in ('unrelated', 'no-inputs', 'external-workspace-2'):
                task = next(n for n in nodes if n.get('displayName') == name)
                assert task.get('memoizationStatus', {}).get('hit'), task
        pods = client._run_api.transport.collection(
            f'/kubernetes/api/v1/namespaces/{namespace}/pods',
            params={
                'labelSelector': 'workflows.argoproj.io/workflow='
                + raw['metadata']['name']
            },
            kubernetes=True,
        )
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
        report.append(
            {
                'run_id': run.run_id,
                'pods': len(pods),
                'workspace_pods': len(mounted),
            }
        )
    print(json.dumps(report, indent=2))
