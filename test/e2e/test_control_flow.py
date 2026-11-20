# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Native control flow: nesting, branches, loops, exit handlers, retries,
container artifacts across a nested boundary and large metadata."""

import pytest
from kfp import dsl

from e2e import support
from e2e.support import COMPONENT


@dsl.component(**COMPONENT)
def number(value: int, fail: bool = False) -> int:
    if fail:
        raise ValueError('deliberate compatibility failure')
    return value


@dsl.component(**COMPONENT)
def total(values: list) -> int:
    assert all(isinstance(value, int) for value in values), values
    return sum(values)


@dsl.container_component
def container_dataset(dataset: dsl.Output[dsl.Dataset]):
    return dsl.ContainerSpec(
        image='busybox:1.36.1',
        command=['sh', '-c'],
        args=['printf "[1,2,3]" > "$1"', 'component', dataset.path],
    )


@dsl.component(**COMPONENT)
def read_dataset(dataset: dsl.Input[dsl.Dataset]) -> int:
    import json

    assert dataset.uri.startswith('s3://'), dataset.uri
    with open(dataset.path) as stream:
        return sum(json.load(stream))


@dsl.pipeline(name='native-container-source')
def container_source() -> dsl.Dataset:
    return container_dataset().set_caching_options(False).outputs['dataset']


@dsl.pipeline(name='native-container-artifacts')
def container_artifacts() -> int:
    source = container_source()
    return read_dataset(dataset=source.output).set_caching_options(False).output


@dsl.component(**COMPONENT)
def large_dataset(dataset: dsl.Output[dsl.Dataset]):
    with open(dataset.path, 'w') as stream:
        stream.write('payload')
    dataset.metadata['large'] = 'x' * 100_000


@dsl.component(**COMPONENT)
def metadata_size(dataset: dsl.Input[dsl.Dataset]) -> int:
    return len(dataset.metadata['large'])


@dsl.pipeline(name='native-large-metadata')
def large_metadata() -> int:
    source = large_dataset().set_caching_options(False)
    return (
        metadata_size(dataset=source.outputs['dataset'])
        .set_caching_options(False)
        .output
    )


@dsl.pipeline(name='native-retry-failure')
def retry_failure():
    number(value=1, fail=True).set_cpu_request('50m').set_memory_limit(
        '64Mi'
    ).set_retry(
        1, backoff_duration='0s', backoff_factor=2.0, policy='OnFailure'
    ).set_caching_options(False)


@dsl.pipeline(name='native-nested')
def nested(value: int) -> int:
    return number(value=value).set_caching_options(False).output


@dsl.component(**COMPONENT)
def report_status(
    status: dsl.PipelineTaskFinalStatus, fail_cleanup: bool = False
) -> str:
    if fail_cleanup:
        raise ValueError('deliberate cleanup failure')
    assert status.state in ('SUCCEEDED', 'FAILED'), status
    assert status.pipeline_task_name, status
    return status.state


@dsl.pipeline(name='native-exit')
def exit_flow(fail: bool = False, fail_cleanup: bool = False):
    cleanup = report_status(fail_cleanup=fail_cleanup).set_caching_options(
        False
    )
    with dsl.ExitHandler(cleanup):
        number(value=42, fail=fail).set_caching_options(False)


@dsl.pipeline(name='native-control-flow')
def control_flow(value: int = 2, fail: bool = False) -> int:
    upstream = nested(value=value)
    with dsl.If(upstream.output > 0):
        number(value=10).set_caching_options(False)
    with dsl.Else():
        number(value=-10).set_caching_options(False)
    with dsl.ParallelFor([1, 2, 3], parallelism=2) as item:
        result = number(value=item, fail=fail).set_caching_options(False)
    return (
        total(values=dsl.Collected(result.output))
        .set_caching_options(False)
        .output
    )


def _root_output(raw):
    return support.node_output(raw['status']['nodes'][raw['metadata']['name']])


@pytest.mark.parametrize(
    'arguments, expected',
    [
        pytest.param({'value': 2}, '6', marks=pytest.mark.smoke, id='branch'),
        pytest.param({'value': -1}, '6', marks=pytest.mark.full, id='else'),
        pytest.param(
            {'fail': True}, None, marks=pytest.mark.smoke, id='loop-failure'
        ),
    ],
)
def test_branches_loops_and_collection(client, record, arguments, expected):
    submitted, done = support.run_pipeline(client, control_flow, arguments)
    raw = support.workflow(client, done)
    assert done.state == ('SUCCEEDED' if expected else 'FAILED'), (
        support.phases(raw)
    )
    skipped = [n for n in support.nodes(raw) if n['phase'] == 'Skipped']
    assert len(skipped) == 1, support.phases(raw)
    assert skipped[0]['displayName'] == (
        'condition-3' if arguments.get('value', 2) > 0 else 'condition-2'
    )
    summed = support.node(raw, 'total')
    assert summed['phase'] == ('Succeeded' if expected else 'Omitted'), summed
    if expected:
        assert _root_output(raw) == expected
    record(run_id=submitted.run_id, state=done.state)


@pytest.mark.parametrize(
    'arguments, cleanup_output',
    [
        pytest.param(
            {'fail': False},
            'SUCCEEDED',
            marks=pytest.mark.full,
            id='body-succeeds',
        ),
        pytest.param(
            {'fail': True}, 'FAILED', marks=pytest.mark.smoke, id='body-fails'
        ),
        pytest.param(
            {'fail_cleanup': True},
            None,
            marks=pytest.mark.full,
            id='cleanup-fails',
        ),
    ],
)
def test_exit_handler_reports_body_status(
    client, record, arguments, cleanup_output
):
    submitted, done = support.run_pipeline(client, exit_flow, arguments)
    raw = support.workflow(client, done)
    expect_failed = arguments.get('fail') or arguments.get('fail_cleanup')
    assert done.state == ('FAILED' if expect_failed else 'SUCCEEDED'), (
        support.phases(raw)
    )
    cleanup = support.node(raw, 'exit')
    assert cleanup['phase'] == ('Succeeded' if cleanup_output else 'Failed'), (
        cleanup
    )
    if cleanup_output:
        assert support.node_output(cleanup) == cleanup_output
    record(run_id=submitted.run_id, state=done.state)


@pytest.mark.smoke
def test_container_artifact_crosses_a_nested_boundary(client, record):
    submitted, done = support.run_pipeline(client, container_artifacts)
    raw = support.workflow(client, done)
    assert done.state == 'SUCCEEDED', support.phases(raw)
    assert _root_output(raw) == '6'
    record(run_id=submitted.run_id, state=done.state)


@pytest.mark.full
def test_large_metadata_stays_out_of_node_status(client, record):
    submitted, done = support.run_pipeline(client, large_metadata)
    raw = support.workflow(client, done)
    assert done.state == 'SUCCEEDED', support.phases(raw)
    assert _root_output(raw) == '100000'
    identities = [
        parameter
        for entry in support.nodes(raw)
        for parameter in entry.get('outputs', {}).get('parameters', [])
        if parameter['name'].startswith('kfp-meta-')
    ]
    assert identities and all(len(p['value']) < 1000 for p in identities)
    record(run_id=submitted.run_id, state=done.state)


@pytest.mark.smoke
def test_retry_attempts_carry_pod_resources(client, record):
    submitted, done = support.run_pipeline(client, retry_failure)
    raw = support.workflow(client, done)
    assert done.state == 'FAILED', support.phases(raw)
    attempts = [n for n in support.nodes(raw) if n['type'] == 'Pod']
    assert len(attempts) == 2 and all(
        n['phase'] == 'Failed' for n in attempts
    ), attempts
    pods = support.pods(client, raw)
    assert len(pods) == 2
    for pod in pods:
        main = support.main_container(pod)
        assert main['resources']['requests']['cpu'] == '50m'
        assert main['resources']['limits']['memory'] == '64Mi'
    record(run_id=submitted.run_id, state=done.state)
