# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Exercise nullable raw-container argv without Python in the user image."""

import base64
import json
from typing import List
from uuid import uuid4

from kfp import dsl

CAPTURE_COMMAND = [
    'sh',
    '-c',
    '{ printf "%s\\n" "$#"; for arg in "$@"; do printf x; printf "%s" "$arg" | base64 | tr -d "\\n"; printf "\\n"; done; } > "$0"',
]


@dsl.container_component
def capture(report: dsl.OutputPath(str), value: str = None):
    return dsl.ContainerSpec(
        image='busybox:1.37',
        command=CAPTURE_COMMAND,
        args=[
            report,
            dsl.IfPresentPlaceholder(
                input_name='value', then=['--value', value], else_=['--absent']
            ),
            dsl.ConcatPlaceholder(
                [
                    'value=',
                    dsl.IfPresentPlaceholder(
                        input_name='value', then=value, else_='absent'
                    ),
                ]
            ),
        ],
    )


@dsl.component
def dataset(value: int, output: dsl.Output[dsl.Dataset]):
    from pathlib import Path

    Path(output.path).write_text(str(value))
    output.metadata['value'] = value


@dsl.container_component
def capture_list(
    datasets: dsl.Input[List[dsl.Dataset]],
    report: dsl.OutputPath(str),
    value: str = None,
):
    return dsl.ContainerSpec(
        image='busybox:1.37',
        command=CAPTURE_COMMAND,
        args=[
            report,
            dsl.IfPresentPlaceholder(
                input_name='datasets',
                then=['--datasets', datasets],
                else_=['--no-datasets'],
            ),
            dsl.IfPresentPlaceholder(
                input_name='value', then=['--value', value], else_=['--absent']
            ),
        ],
    )


@dsl.pipeline(name='container-optional-compatibility')
def pipeline(value: str = None, values: list = [1, 2]) -> str:
    result = capture(value=value)
    with dsl.ParallelFor(values) as item:
        produced = dataset(value=item)
    capture_list(datasets=dsl.Collected(produced.output), value=value)
    return result.output


def argv(done, name):
    task = next(task for task in done.tasks if task.display_name == name)
    output = next(
        parameter.value
        for parameter in task.outputs.parameters
        if parameter.parameter_key == 'report'
    )
    lines = output.splitlines()
    actual = [base64.b64decode(line[1:]).decode() for line in lines[1:]]
    assert int(lines[0]) == len(actual)
    return actual


def verify(client):
    report = []
    cases = [
        (value, [1, 2])
        for value in [None, '', 'null', 'quote " slash \\ braces {{x}}\nend']
    ] + [(None, [])]
    for value, values in cases:
        result = client.create_run_from_pipeline_func(
            pipeline,
            arguments={
                'values': values,
                **({} if value is None else {'value': value}),
            },
            run_name='Container optional ' + uuid4().hex[:8],
            experiment_name='SDK backwards compatibility',
            namespace=client.get_user_namespace(),
        )
        done = result.wait_for_run_completion(timeout=300)
        assert done.state == 'SUCCEEDED', done.to_dict()
        actual = argv(done, 'capture')
        expected = (
            ['--absent', 'value=absent']
            if value is None
            else ['--value', value, 'value=' + value]
        )
        assert actual == expected, (actual, expected)
        staged = argv(done, 'capture-list')
        if values:
            assert staged[0] == '--datasets'
            artifacts = json.loads(staged[1])
            assert [item['metadata']['value'] for item in artifacts] == values
            assert all(
                item['uri'].startswith('s3://')
                and item['customPath'].startswith('/tmp/kfp/artifact-lists/')
                for item in artifacts
            )
            tail = staged[2:]
        else:
            assert staged[0] == '--no-datasets'
            tail = staged[1:]
        assert tail == (['--absent'] if value is None else ['--value', value])
        report.append(
            {
                'run_id': result.run_id,
                'value': value,
                'argv': actual,
                'state': done.state,
            }
        )
    return report


@dsl.component
def maybe(fail: bool) -> str:
    if fail:
        raise RuntimeError('deliberate failure')
    return 'ok'


@dsl.pipeline(name='container-tolerant-compatibility')
def tolerant_pipeline(fail: bool = True) -> str:
    """A raw container consumes a possibly failed producer: IfPresent decides."""
    source = maybe(fail=fail).set_caching_options(False)
    return (
        capture(value=source.output)
        .ignore_upstream_failure()
        .set_caching_options(False)
        .output
    )
