# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Exercise native init/volume/security/affinity settings without a KFP driver."""

import json
import os
import subprocess
from uuid import uuid4

import kfp
from kfp import dsl, kubernetes


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


if __name__ == '__main__':
    namespace = os.environ.get('KFP_TEST_NAMESPACE', 'kfp-argo')
    config = 'sdk-native-settings-' + uuid4().hex[:8]
    subprocess.run(
        [
            'kubectl',
            '--context',
            'orbstack',
            '-n',
            namespace,
            'create',
            'configmap',
            config,
            '--from-literal=value=configured',
        ],
        check=True,
    )
    client = kfp.Client(
        host=os.environ.get('KFP_TEST_HOST', 'http://127.0.0.1:3003'),
        namespace=namespace,
        existing_token=os.environ['KFP_TEST_TOKEN'],
    )
    run = client.create_run_from_pipeline_func(
        pipeline,
        arguments={'config_name': config},
        run_name='Kubernetes settings ' + uuid4().hex[:8],
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
        (n.get('displayName'), n.get('phase'), n.get('message')) for n in nodes
    ]
    task = next(n for n in nodes if n.get('displayName') == 'check')
    assert json.loads(
        next(
            p['value']
            for p in task['outputs']['parameters']
            if p['name'] == 'result'
        )
    ) == {'uid': 1000, 'init': 'prepared', 'config': 'configured'}
    pods = client._run_api.transport.collection(
        f'/kubernetes/api/v1/namespaces/{namespace}/pods',
        params={
            'labelSelector': 'workflows.argoproj.io/workflow='
            + raw['metadata']['name']
        },
        kubernetes=True,
    )
    assert len(pods) == 1, len(pods)
    main = next(c for c in pods[0]['spec']['containers'] if c['name'] == 'main')
    assert main['securityContext']['allowPrivilegeEscalation'] is False
    assert main['securityContext']['capabilities']['drop'] == ['ALL']
    assert main['securityContext']['seccompProfile']['type'] == 'RuntimeDefault'
    assert any(
        t.get('key') == 'compatibility-fixture' and t['tolerationSeconds'] == 60
        for t in pods[0]['spec']['tolerations']
    )
    print(
        json.dumps(
            {
                'run_id': run.run_id,
                'state': done.state,
                'pods': len(pods),
                'config_map': config,
            }
        )
    )
