# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""TaskConfig projection without driver pods, including dynamic resource claims
whose pod fields are checked without claiming a device."""

import time
from uuid import uuid4

import pytest
from kfp import dsl, kubernetes

from e2e import support


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


@pytest.mark.full
def test_task_config_projection_respects_apply_to_task(client, record):
    submitted, done = support.run_pipeline(client, pipeline, timeout=300)
    raw = support.workflow(client, done)
    assert done.state == 'SUCCEEDED', support.phases(raw)
    pods = support.pods(client, raw)
    assert len(pods) == 2, len(pods)
    for entry in support.nodes(raw):
        if entry.get('displayName') not in ('external', 'both'):
            continue
        pod = next(
            p
            for p in pods
            if p['metadata']['annotations']['workflows.argoproj.io/node-id']
            == entry['id']
        )
        main = support.main_container(pod)
        if entry['displayName'] == 'external':
            assert 'cpu' not in main.get('resources', {}).get('limits', {})
            assert 'example.invalid/target' not in pod['spec'].get(
                'nodeSelector', {}
            )
            assert not pod['spec'].get('resourceClaims')
            assert not main.get('resources', {}).get('claims')
        else:
            assert main['resources']['limits']['cpu'] == '2'
            assert pod['spec']['nodeSelector']['kubernetes.io/os'] == 'linux'
    record(run_id=submitted.run_id, state=done.state, pods=len(pods))


@pytest.mark.full
def test_resource_claim_pod_fields_without_allocation(client, record):
    """Pod fields are checked while the pod waits for a claim template that
    does not exist; the owned run is then terminated."""
    version = client._run_api.transport.request('GET', '/kubernetes/version')
    minor = int(version['minor'].rstrip('+'))
    if minor < 34:
        # DynamicResourceAllocation is gated off by default before 1.34, and
        # the API server drops the pod's claim fields; stock ran its DRA lane
        # on 1.34 as well (P01).
        pytest.skip(
            f'Kubernetes 1.{minor} drops resourceClaims without the DRA gate'
        )
    name = 'kfp-unavailable-' + uuid4().hex[:8]
    submitted = support.submit(
        client,
        claim_pipeline,
        {'claims': [{'resourceClaimTemplateName': name}]},
    )
    try:
        deadline = time.monotonic() + 60
        pods = []
        while not pods and time.monotonic() < deadline:
            info = client.get_run(submitted.run_id)
            assert info.state != 'FAILED', support.failures(info)
            pods = support.pods(
                client, {'metadata': info.pipeline_spec['metadata']}
            )
            if not pods:
                time.sleep(2)
        assert len(pods) == 1, pods
        assert pods[0]['spec']['resourceClaims'] == [
            {'name': name, 'resourceClaimTemplateName': name}
        ]
        assert support.main_container(pods[0])['resources']['claims'] == [
            {'name': name}
        ]
        record(
            run_id=submitted.run_id,
            pod_fields_verified=True,
            device_allocation_verified=False,
        )
    finally:
        client.terminate_run(submitted.run_id)
