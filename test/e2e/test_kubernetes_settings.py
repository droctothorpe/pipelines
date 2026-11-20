# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""kfp-kubernetes settings lowered without a KFP driver: init containers,
volumes, ConfigMaps, field paths, security context, affinity, tolerations."""

from uuid import uuid4

import pytest
from kfp import dsl, kubernetes

from e2e import support


@dsl.container_component
def check(result: dsl.OutputPath(dict)):
    return dsl.ContainerSpec(
        image='python:3.11',
        command=['python3', '-c'],
        args=[
            'import os,json,pathlib,sys; '
            'assert os.getuid()==1000; '
            'assert pathlib.Path("/scratch/value").read_text()=="prepared"; '
            'assert pathlib.Path("/config/value").read_text()=="configured"; '
            'assert os.environ["CONFIG_VALUE"]=="configured"; '
            'assert os.environ["POD_NAME"]; '
            'pathlib.Path(sys.argv[1]).write_text(json.dumps({"uid":os.getuid(),"init":"prepared","config":"configured"}))',
            result,
        ],
    )


@dsl.pipeline(name='native-kubernetes-settings-compatibility')
def pipeline(
    config_name: str,
    selector: dict = {'kubernetes.io/os': 'linux'},
    toleration: dict = {
        'key': 'compatibility-fixture',
        'operator': 'Exists',
        'effect': 'NoExecute',
        'tolerationSeconds': 60,
    },
    affinity: dict = {
        'preferredDuringSchedulingIgnoredDuringExecution': [
            {
                'weight': 50,
                'preference': {
                    'matchExpressions': [
                        {
                            'key': 'kubernetes.io/os',
                            'operator': 'In',
                            'values': ['linux'],
                        }
                    ]
                },
            }
        ]
    },
    cpu: str = '100m',
):
    task = check().set_cpu_limit(cpu)
    kubernetes.add_node_selector_json(task, selector)
    kubernetes.empty_dir_mount(task, 'scratch', '/scratch', size_limit='1Mi')
    kubernetes.add_init_container(
        task,
        'prepare',
        'python:3.11',
        command=[
            'python3',
            '-c',
            'import os,pathlib;pathlib.Path("/scratch/value").write_text(os.environ["VALUE"])',
        ],
        env={'VALUE': 'prepared'},
        volume_mounts={'scratch': '/scratch'},
        resource_requests={'cpu': '10m'},
    )
    kubernetes.use_config_map_as_volume(task, config_name, '/config')
    kubernetes.use_config_map_as_env(
        task, config_name, {'value': 'CONFIG_VALUE'}
    )
    kubernetes.use_field_path_as_env(task, 'POD_NAME', 'metadata.name')
    kubernetes.set_security_context(
        task, run_as_user=1000, run_as_group=1000, run_as_non_root=True
    )
    kubernetes.add_node_affinity_json(task, affinity)
    kubernetes.add_toleration_json(task, toleration)


@pytest.fixture
def config_map(client, namespace):
    """A ConfigMap owned by the test, created and removed through the proxy."""
    name = 'sdk-native-settings-' + uuid4().hex[:8]
    path = f'/kubernetes/api/v1/namespaces/{namespace}/configmaps'
    client._run_api.transport.request(
        'POST',
        path,
        body={
            'apiVersion': 'v1',
            'kind': 'ConfigMap',
            'metadata': {'name': name},
            'data': {'value': 'configured'},
        },
    )
    yield name
    client._run_api.transport.request('DELETE', f'{path}/{name}')


@pytest.mark.full
def test_settings_reach_the_pod(client, record, config_map):
    submitted, done = support.run_pipeline(
        client, pipeline, {'config_name': config_map}, timeout=300
    )
    raw = support.workflow(client, done)
    assert done.state == 'SUCCEEDED', support.phases(raw)
    import json

    assert json.loads(
        support.node_output(support.node(raw, 'check'), 'result')
    ) == {
        'uid': 1000,
        'init': 'prepared',
        'config': 'configured',
    }
    pods = support.pods(client, raw)
    assert len(pods) == 1, len(pods)
    main = support.main_container(pods[0])
    assert main['securityContext']['allowPrivilegeEscalation'] is False
    assert main['securityContext']['capabilities']['drop'] == ['ALL']
    assert main['securityContext']['seccompProfile']['type'] == 'RuntimeDefault'
    assert any(
        t.get('key') == 'compatibility-fixture' and t['tolerationSeconds'] == 60
        for t in pods[0]['spec']['tolerations']
    )
    record(run_id=submitted.run_id, state=done.state, config_map=config_map)
