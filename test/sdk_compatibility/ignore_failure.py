# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Verify cleanup defaults, successful inputs, and failure propagation live."""

import json
import os
from uuid import uuid4

import kfp
from kfp import dsl


@dsl.component
def produce(fail: bool, data: dsl.Output[dsl.Dataset]) -> str:
    from pathlib import Path

    if fail:
        raise RuntimeError('intentional compatibility failure')
    Path(data.path).write_text('payload')
    data.metadata['checked'] = True
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
    with dsl.If(fail == True):
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
    """The producer is outside the condition; the tolerant consumer inside."""
    source = produce(fail=fail).set_caching_options(False)
    with dsl.If(enabled == True):
        check_status(failed=fail).after(
            source
        ).ignore_upstream_failure().set_caching_options(False)
        cleanup(
            failed=fail,
            message=source.outputs['Output'],
            optional=source.outputs['Output'],
            data=source.outputs['data'],
        ).ignore_upstream_failure().set_caching_options(False)


if __name__ == '__main__':
    namespace = os.environ.get('KFP_TEST_NAMESPACE', 'kfp-argo')
    client = kfp.Client(
        host=os.environ.get('KFP_TEST_HOST', 'http://127.0.0.1:3003'),
        namespace=namespace,
        existing_token=os.environ['KFP_TEST_TOKEN'],
    )
    report = []
    for function, fail in [
        (pipeline, True),
        (pipeline, False),
        (grouped_pipeline, True),
        (crossing_pipeline, True),
        (crossing_pipeline, False),
    ]:
        run = client.create_run_from_pipeline_func(
            function,
            arguments={'fail': fail},
            run_name='Failure cleanup compatibility ' + uuid4().hex[:8],
            experiment_name='SDK backwards compatibility',
            namespace=namespace,
        )
        complete = run.wait_for_run_completion(timeout=300)
        raw = client._run_api.transport.request(
            'GET',
            f'/argo/api/v1/workflows/{namespace}/{complete.pipeline_spec["metadata"]["name"]}',
        )
        nodes = list(raw['status']['nodes'].values())
        cleanups = [
            node for node in nodes if node.get('displayName') == 'cleanup'
        ]
        assert len(cleanups) == 1, nodes
        assert cleanups[0]['phase'] == 'Succeeded', cleanups[0]
        for status_node in (
            node for node in nodes if node.get('displayName') == 'check-status'
        ):
            assert status_node['phase'] == 'Succeeded', status_node
        output = next(
            p['value']
            for p in cleanups[0]['outputs']['parameters']
            if p['name'] == 'Output'
        )
        assert output == 'cleanup verified', output
        assert complete.state == ('FAILED' if fail else 'SUCCEEDED'), (
            complete.to_dict()
        )
        report.append(
            {
                'run_id': run.run_id,
                'pipeline': function.name,
                'fail': fail,
                'state': complete.state,
                'cleanup_output': output,
            }
        )
    print(json.dumps(report, indent=2))
