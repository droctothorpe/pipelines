# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""TaskConfig projection without driver pods, including dynamic resources."""

import json
import os
from uuid import uuid4

import kfp
from kfp import dsl, kubernetes


@dsl.component(
    task_config_passthroughs=[
        dsl.TaskConfigPassthrough(dsl.TaskConfigField.RESOURCES),
        dsl.TaskConfigPassthrough(dsl.TaskConfigField.ENV),
        dsl.TaskConfigPassthrough(dsl.TaskConfigField.KUBERNETES_NODE_SELECTOR),
        dsl.TaskConfigPassthrough(
            dsl.TaskConfigField.KUBERNETES_RESOURCE_CLAIMS
        ),
    ]
)
def external(config: dsl.TaskConfig, cpu: str) -> dict:
    import os

    assert config.resources['limits']['cpu'] == cpu, config
    assert config.env == [{'name': 'EXTERNAL_VALUE', 'value': 'configured'}], (
        config
    )
    assert config.node_selector == {'example.invalid/target': 'external'}, (
        config
    )
    assert config.resource_claims == [
        {
            'name': 'external-template',
            'resourceClaimTemplateName': 'external-template',
        }
    ], config
    assert os.environ.get('EXTERNAL_VALUE') is None
    assert os.environ.get('KFP_ARGO_RUN_UID')
    return {'cpu': cpu, 'mode': 'external-only'}


@dsl.component(
    task_config_passthroughs=[
        dsl.TaskConfigPassthrough(
            dsl.TaskConfigField.RESOURCES, apply_to_task=True
        ),
        dsl.TaskConfigPassthrough(dsl.TaskConfigField.ENV, apply_to_task=True),
        dsl.TaskConfigPassthrough(
            dsl.TaskConfigField.KUBERNETES_NODE_SELECTOR, apply_to_task=True
        ),
    ]
)
def both(config: dsl.TaskConfig, cpu: str) -> dict:
    import os

    assert config.resources['limits']['cpu'] == cpu, config
    assert config.env == [{'name': 'EXTERNAL_VALUE', 'value': 'configured'}], (
        config
    )
    assert config.node_selector == {'kubernetes.io/os': 'linux'}, config
    assert os.environ.get('EXTERNAL_VALUE') == 'configured'
    return {'cpu': cpu, 'mode': 'both'}


@dsl.pipeline(name='task-config-compatibility')
def pipeline(
    cpu: str = '2',
    external_selector: dict = {'example.invalid/target': 'external'},
    pod_selector: dict = {'kubernetes.io/os': 'linux'},
    claims: list = [{'resourceClaimTemplateName': 'external-template'}],
):
    first = (
        external(cpu=cpu)
        .set_cpu_limit(cpu)
        .set_env_variable('EXTERNAL_VALUE', 'configured')
    )
    kubernetes.add_node_selector_json(first, external_selector)
    kubernetes.add_resource_claim_json(first, claims)
    second = (
        both(cpu=cpu)
        .set_cpu_limit(cpu)
        .set_env_variable('EXTERNAL_VALUE', 'configured')
    )
    kubernetes.add_node_selector_json(second, pod_selector)


@dsl.container_component
def claim_task():
    return dsl.ContainerSpec(
        image='python:3.11', command=['python3', '-c', 'pass']
    )


@dsl.pipeline(name='native-dra-shape-compatibility')
def claim_pipeline(claims: list):
    kubernetes.add_resource_claim_json(claim_task(), claims)


def verify_claim_shape(client):
    """Check native Pod fields without claiming device allocation; stop the owned run."""
    import time

    namespace = client.get_user_namespace()
    name = 'kfp-unavailable-' + uuid4().hex[:8]
    run = client.create_run_from_pipeline_func(
        claim_pipeline,
        arguments={'claims': [{'resourceClaimTemplateName': name}]},
        run_name='DRA shape ' + uuid4().hex[:8],
        experiment_name='SDK backwards compatibility',
        namespace=namespace,
    )
    try:
        deadline = time.monotonic() + 60
        pods = []
        while not pods and time.monotonic() < deadline:
            info = client.get_run(run.run_id)
            if info.state == 'FAILED':
                raise AssertionError(
                    [
                        (t.display_name, t.lifecycle_message)
                        for t in (info.tasks or [])
                    ]
                )
            pods = client._run_api.transport.collection(
                f'/kubernetes/api/v1/namespaces/{namespace}/pods',
                params={
                    'labelSelector': 'workflows.argoproj.io/workflow='
                    + info.pipeline_spec['metadata']['name']
                },
                kubernetes=True,
            )
            if not pods:
                time.sleep(2)
        assert len(pods) == 1, pods
        pod = pods[0]
        assert pod['spec']['resourceClaims'] == [
            {'name': name, 'resourceClaimTemplateName': name}
        ]
        main = next(c for c in pod['spec']['containers'] if c['name'] == 'main')
        assert main['resources']['claims'] == [{'name': name}]
        return {
            'run_id': run.run_id,
            'pod_fields_verified': True,
            'device_allocation_verified': False,
        }
    finally:
        client.terminate_run(run.run_id)


if __name__ == '__main__':
    namespace = os.environ.get('KFP_TEST_NAMESPACE', 'kfp-argo')
    client = kfp.Client(
        host=os.environ.get('KFP_TEST_HOST', 'http://127.0.0.1:3003'),
        namespace=namespace,
        existing_token=os.environ['KFP_TEST_TOKEN'],
    )
    run = client.create_run_from_pipeline_func(
        pipeline,
        arguments={},
        run_name='TaskConfig compatibility ' + uuid4().hex[:8],
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
    pods = client._run_api.transport.collection(
        f'/kubernetes/api/v1/namespaces/{namespace}/pods',
        params={
            'labelSelector': 'workflows.argoproj.io/workflow='
            + raw['metadata']['name']
        },
        kubernetes=True,
    )
    assert len(pods) == 2, len(pods)
    for node in nodes:
        if node.get('displayName') not in ('external', 'both'):
            continue
        pod = next(
            p
            for p in pods
            if p['metadata']['annotations']['workflows.argoproj.io/node-id']
            == node['id']
        )
        main = next(c for c in pod['spec']['containers'] if c['name'] == 'main')
        if node['displayName'] == 'external':
            assert 'cpu' not in main.get('resources', {}).get('limits', {})
            assert 'example.invalid/target' not in pod['spec'].get(
                'nodeSelector', {}
            )
            assert not pod['spec'].get('resourceClaims')
            assert not main.get('resources', {}).get('claims')
        else:
            assert main['resources']['limits']['cpu'] == '2'
            assert pod['spec']['nodeSelector']['kubernetes.io/os'] == 'linux'
    print(
        json.dumps(
            {'run_id': run.run_id, 'state': done.state, 'pods': len(pods)}
        )
    )
