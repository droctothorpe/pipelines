# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Failure tolerance: cleanup defaults, successful inputs, final status, and
producers outside the consumer's group (C04/C28)."""

import pytest
from kfp import dsl

from e2e import support


@dsl.component
def produce(fail: bool, data: dsl.Output[dsl.Dataset]) -> str:
    from pathlib import Path

    Path(data.path).write_text('payload')
    data.metadata['checked'] = True
    if fail:
        raise RuntimeError('deliberate failure')
    return 'null'


@dsl.component
def cleanup(
    failed: bool,
    message: str = 'fallback',
    optional: str = None,
    data: dsl.Input[dsl.Dataset] = None,
) -> str:
    from pathlib import Path

    assert message == ('fallback' if failed else 'null'), message
    assert optional == (None if failed else 'null'), repr(optional)
    if failed:
        assert data is None
    else:
        assert Path(data.path).read_text() == 'payload'
        assert data.metadata['checked'] is True
    return 'cleanup verified'


@dsl.component
def check_status(failed: bool, status: dsl.PipelineTaskFinalStatus) -> str:
    assert status.state == ('FAILED' if failed else 'SUCCEEDED'), status
    assert status.pipeline_job_resource_name
    return status.state


@dsl.pipeline(name='ignore-failure-compatibility')
def pipeline(fail: bool):
    source = produce(fail=fail).set_caching_options(False)
    check_status(failed=fail).after(
        source
    ).ignore_upstream_failure().set_caching_options(False)
    cleanup(
        failed=fail,
        message=source.outputs['Output'],
        optional=source.outputs['Output'],
        data=source.outputs['data'],
    ).ignore_upstream_failure().set_caching_options(False)


@dsl.pipeline(name='grouped-ignore-failure-compatibility')
def grouped_pipeline(fail: bool):
    with dsl.If(fail == True):  # noqa: E712
        source = produce(fail=fail).set_caching_options(False)
        check_status(failed=fail).after(
            source
        ).ignore_upstream_failure().set_caching_options(False)
        cleanup(
            failed=fail,
            message=source.outputs['Output'],
            optional=source.outputs['Output'],
            data=source.outputs['data'],
        ).ignore_upstream_failure().set_caching_options(False)


@dsl.pipeline(name='crossing-ignore-failure-compatibility')
def crossing_pipeline(fail: bool, enabled: bool = True):
    """The producer is outside the condition; the tolerant consumers inside."""
    source = produce(fail=fail).set_caching_options(False)
    with dsl.If(enabled == True):  # noqa: E712
        check_status(failed=fail).after(
            source
        ).ignore_upstream_failure().set_caching_options(False)
        cleanup(
            failed=fail,
            message=source.outputs['Output'],
            optional=source.outputs['Output'],
            data=source.outputs['data'],
        ).ignore_upstream_failure().set_caching_options(False)


@pytest.mark.parametrize(
    'function, fail',
    [
        pytest.param(
            pipeline, True, marks=pytest.mark.smoke, id='sibling-failed'
        ),
        pytest.param(
            pipeline, False, marks=pytest.mark.full, id='sibling-succeeded'
        ),
        pytest.param(
            grouped_pipeline, True, marks=pytest.mark.full, id='grouped-failed'
        ),
        pytest.param(
            crossing_pipeline,
            True,
            marks=pytest.mark.smoke,
            id='crossing-failed',
        ),
        pytest.param(
            crossing_pipeline,
            False,
            marks=pytest.mark.full,
            id='crossing-succeeded',
        ),
    ],
)
def test_cleanup_runs_with_defaults_after_upstream_failure(
    client, record, function, fail
):
    submitted, done = support.run_pipeline(
        client, function, {'fail': fail}, timeout=300
    )
    raw = support.workflow(client, done)
    cleanups = [
        n for n in support.nodes(raw) if n.get('displayName') == 'cleanup'
    ]
    assert len(cleanups) == 1, support.phases(raw)
    assert cleanups[0]['phase'] == 'Succeeded', cleanups[0]
    assert support.node_output(cleanups[0]) == 'cleanup verified'
    status = support.node(raw, 'check-status')
    assert status['phase'] == 'Succeeded', status
    assert support.node_output(status) == ('FAILED' if fail else 'SUCCEEDED')
    assert done.state == ('FAILED' if fail else 'SUCCEEDED'), support.phases(
        raw
    )
    record(
        run_id=submitted.run_id,
        pipeline=function.name,
        fail=fail,
        state=done.state,
    )
