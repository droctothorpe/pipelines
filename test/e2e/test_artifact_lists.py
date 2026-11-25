# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Dynamic artifact lists: staged files and directories, cache reuse,
credential isolation, iteration over produced lists, raw and shell consumers,
and imported lists."""

from uuid import uuid4

import pytest

from e2e import support
from e2e.pipelines.artifact_lists import (
    imported_pipeline,
    iteration_pipeline,
    nested_iteration_pipeline,
    nested_pipeline,
    pipeline,
    raw_pipeline,
    shell_pipeline,
)


def _staged(client, function, values, directory, expected=None):
    arguments = {'values': values, 'directory': directory, 'nonce': uuid4().hex}
    if expected is not None:
        arguments['expected'] = expected
    submitted = support.submit(client, function, arguments)
    done, raw = support.wait_without_errors(client, submitted, 300)
    assert done.state == 'SUCCEEDED', support.phases(raw)
    consumer = support.node(raw, 'consume')
    assert support.node_output(consumer) == str(sum(expected or values))
    pods = support.pods(client, raw)
    staging = next(
        p
        for p in pods
        if any(
            c['name'] == 'kfp-stage-artifacts'
            for c in p['spec'].get('initContainers', [])
        )
    )
    main = support.main_container(staging)
    stage = next(
        c
        for c in staging['spec']['initContainers']
        if c['name'] == 'kfp-stage-artifacts'
    )
    secret_volumes = {
        v['name'] for v in staging['spec']['volumes'] if 'secret' in v
    }
    assert not any(m['name'] in secret_volumes for m in main['volumeMounts']), (
        'Storage secrets must not be mounted in main'
    )
    assert any(
        m['name'] in secret_volumes and m.get('readOnly')
        for m in stage['volumeMounts']
    )
    return submitted, raw, pods


@pytest.mark.smoke
def test_staged_lists_cache_producers_and_isolate_credentials(client, record):
    first, raw, _ = _staged(client, pipeline, [1, 2], False)
    record(run_id=first.run_id, pods='cold')
    second, raw, pods = _staged(client, pipeline, [1, 2], False)
    assert len(pods) == 1, (
        'Cached producers create no pods; only the consumer is new'
    )
    assert all(
        n.get('memoizationStatus', {}).get('hit')
        for n in support.nodes(raw)
        if n.get('displayName') == 'produce'
    )
    record(run_id=second.run_id, pods=len(pods))


@pytest.mark.full
@pytest.mark.parametrize(
    'function, values, directory',
    [
        pytest.param(pipeline, [1, 2], True, id='directories'),
        pytest.param(pipeline, [], False, id='empty'),
        pytest.param(nested_pipeline, [3, 4], True, id='nested'),
        pytest.param(pipeline, [1] * 256, False, id='256-items'),
    ],
)
def test_staged_list_shapes(client, record, function, values, directory):
    expected = (
        [v for v in values for _ in range(2)]
        if function is nested_pipeline
        else None
    )
    submitted, _, pods = _staged(client, function, values, directory, expected)
    record(run_id=submitted.run_id, pipeline=function.name, pods=len(pods))


@pytest.mark.full
@pytest.mark.parametrize(
    'function, arguments',
    [
        pytest.param(iteration_pipeline, {'values': [1, 2]}, id='iterate'),
        pytest.param(iteration_pipeline, {'values': []}, id='iterate-empty'),
        pytest.param(
            nested_iteration_pipeline,
            {'values': [3, 4], 'expected': [3, 3, 4, 4]},
            id='iterate-nested',
        ),
    ],
)
def test_iteration_over_produced_artifact_lists(
    client, record, function, arguments
):
    submitted, done = support.run_pipeline(
        client, function, arguments, timeout=300
    )
    assert done.state == 'SUCCEEDED', support.failures(done)
    assert support.task_output(support.task(done, 'check-numbers')) == sum(
        arguments.get('expected', arguments['values'])
    )
    record(run_id=submitted.run_id, pipeline=function.name, state=done.state)


@pytest.mark.full
@pytest.mark.parametrize(
    'values, directory',
    [([1, 2], False), ([1, 2], True), ([], False)],
    ids=['files', 'directories', 'empty'],
)
def test_raw_container_consumes_staged_lists(client, record, values, directory):
    submitted, done = support.run_pipeline(
        client,
        raw_pipeline,
        {'values': values, 'directory': directory, 'nonce': uuid4().hex},
        timeout=300,
    )
    assert done.state == 'SUCCEEDED', support.failures(done)
    assert support.task_output(
        support.task(done, 'raw-consume'), 'total'
    ) == sum(values)
    record(run_id=submitted.run_id, values=len(values), directory=directory)


@pytest.mark.full
def test_shell_consumer_without_python(client, record):
    submitted, done = support.run_pipeline(client, shell_pipeline, timeout=300)
    assert done.state == 'SUCCEEDED', support.failures(done)
    assert (
        support.task_output(support.task(done, 'shell-consume'), 'output')
        == 'shell-verified'
    )
    record(run_id=submitted.run_id, state=done.state)


@pytest.mark.full
@pytest.mark.parametrize(
    'uri, succeeds',
    [
        (
            'https://raw.githubusercontent.com/kubeflow/pipelines/7780f12acfbde9f16169c7fcbfdfb6c3ef5432ea/README.md',
            True,
        ),
        ('s3://argo-artifacts/missing-artifact-list-' + uuid4().hex, False),
    ],
    ids=['public-http', 'missing-object'],
)
def test_imported_lists_stage_or_fail_visibly(client, record, uri, succeeds):
    submitted, done = support.run_pipeline(
        client, imported_pipeline, {'uri': uri}, timeout=300
    )
    raw = support.workflow(client, done)
    assert done.state == ('SUCCEEDED' if succeeds else 'FAILED'), (
        support.phases(raw)
    )
    if not succeeds:
        consumer = support.node(raw, 'check-imports')
        assert 'kfp-stage-artifacts' in consumer.get('message', ''), consumer
    record(run_id=submitted.run_id, expected_success=succeeds, state=done.state)
