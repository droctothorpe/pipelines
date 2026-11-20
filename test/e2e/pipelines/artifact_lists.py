# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Dynamic artifact list pipelines: staged, nested, iterated, raw, shell and imported."""

from typing import List

from kfp import dsl, kubernetes


@dsl.component
def produce(value: int, directory: bool, data: dsl.Output[dsl.Dataset]):
    from pathlib import Path

    path = Path(data.path)
    if directory:
        path.mkdir()
        path = path / 'value.txt'
    path.write_text(str(value))
    data.metadata['value'] = value
    data.metadata['directory'] = directory


@dsl.component
def consume(
    values: dsl.Input[List[dsl.Dataset]], expected: list, nonce: str
) -> int:
    from pathlib import Path

    assert isinstance(values, list), type(values)
    actual = []
    for value in values:
        path = Path(value.path)
        if value.metadata['directory']:
            path = path / 'value.txt'
        number = int(path.read_text())
        assert number == value.metadata['value']
        assert value.uri.startswith('s3://')
        actual.append(number)
    assert actual == expected, (actual, expected)
    return sum(actual)


@dsl.pipeline(name='artifact-list-staging-compatibility')
def pipeline(
    values: list,
    nonce: str,
    directory: bool = False,
    selector: dict = {'kubernetes.io/os': 'linux'},
):
    with dsl.ParallelFor(values) as value:
        task = produce(value=value, directory=directory)
    consumer = consume(
        values=dsl.Collected(task.outputs['data']), expected=values, nonce=nonce
    )
    kubernetes.add_node_selector_json(consumer, selector)


@dsl.pipeline
def forward(
    values: dsl.Input[List[dsl.Dataset]], expected: list, nonce: str
) -> List[dsl.Dataset]:
    consume(values=values, expected=expected, nonce=nonce)
    return values


@dsl.pipeline(name='nested-artifact-list-staging-compatibility')
def nested_pipeline(
    values: list, expected: list, nonce: str, directory: bool = True
):
    with dsl.ParallelFor(values) as value:
        with dsl.ParallelFor([0, 1]):
            task = produce(value=value, directory=directory)
    with dsl.If(directory == True):  # noqa: E712
        forwarded = forward(
            values=dsl.Collected(task.outputs['data']),
            expected=expected,
            nonce=nonce,
        )
        consume(values=forwarded.output, expected=expected, nonce=nonce)


@dsl.component
def read_one(data: dsl.Input[dsl.Dataset]) -> int:
    from pathlib import Path

    path = Path(data.path)
    if data.metadata['directory']:
        path = path / 'value.txt'
    value = int(path.read_text())
    assert value == data.metadata['value']
    return value


@dsl.component
def check_numbers(values: list, expected: list) -> int:
    assert values == expected, (values, expected)
    return sum(values)


@dsl.pipeline
def generate_artifacts(
    values: list, directory: bool = False
) -> List[dsl.Dataset]:
    with dsl.ParallelFor(values) as value:
        task = produce(value=value, directory=directory)
    return dsl.Collected(task.outputs['data'])


@dsl.pipeline
def generate_nested_artifacts(values: list) -> List[dsl.Dataset]:
    with dsl.ParallelFor(values) as value:
        with dsl.ParallelFor([0, 1]):
            task = produce(value=value, directory=True)
    return dsl.Collected(task.outputs['data'])


@dsl.pipeline
def read_nested(data: dsl.Input[dsl.Dataset]) -> int:
    return read_one(data=data).output


@dsl.pipeline(name='artifact-iteration-compatibility')
def iteration_pipeline(values: list, directory: bool = False):
    generated = generate_artifacts(values=values, directory=directory)
    with dsl.ParallelFor(generated.output) as artifact:
        result = read_nested(data=artifact)
    check_numbers(values=dsl.Collected(result.output), expected=values)


@dsl.pipeline(name='nested-artifact-iteration-compatibility')
def nested_iteration_pipeline(values: list, expected: list):
    generated = generate_nested_artifacts(values=values)
    with dsl.ParallelFor(generated.output) as artifact:
        result = read_nested(data=artifact)
    check_numbers(values=dsl.Collected(result.output), expected=expected)


@dsl.container_component
def raw_consume(
    values: dsl.Input[List[dsl.Dataset]],
    expected: list,
    nonce: str,
    total: dsl.OutputPath(int),
    report: dsl.Output[dsl.Dataset],
):
    return dsl.ContainerSpec(
        image='python:3.11',
        command=[
            'python3',
            '-c',
            'import json,pathlib,sys; artifacts=json.loads(sys.argv[1]); expected=json.loads(sys.argv[2]); '
            'actual=[int((pathlib.Path(a["customPath"])/"value.txt" if a["metadata"]["directory"] else pathlib.Path(a["customPath"])).read_text()) for a in artifacts]; '
            'assert actual==expected,(actual,expected); '
            'assert all(a["type"]["schemaTitle"]=="system.Dataset" and a["uri"].startswith("s3://") for a in artifacts); '
            'assert sys.argv[5].startswith("s3://"); '
            'pathlib.Path(sys.argv[3]).write_text(str(sum(actual))); pathlib.Path(sys.argv[4]).write_text("raw list verified")',
        ],
        args=[values, expected, total, report.path, report.uri],
    )


@dsl.component
def check_report(report: dsl.Input[dsl.Dataset]) -> str:
    from pathlib import Path

    assert Path(report.path).read_text() == 'raw list verified'
    return 'verified'


@dsl.pipeline(name='raw-artifact-list-compatibility')
def raw_pipeline(values: list, nonce: str, directory: bool = False):
    with dsl.ParallelFor(values) as value:
        task = produce(value=value, directory=directory)
    result = raw_consume(
        values=dsl.Collected(task.outputs['data']), expected=values, nonce=nonce
    )
    check_report(report=result.outputs['report'])


@dsl.container_component
def shell_consume(
    values: dsl.Input[List[dsl.Dataset]], output: dsl.OutputPath(str)
):
    script = r"""test -z "$(command -v python3)" || exit 9
path=$(printf '%s' "$1" | sed -n 's/.*"customPath": "\([^"]*\)".*/\1/p')
test "$(cat "$path")" = 2
printf shell-verified > "$2"
"""
    return dsl.ContainerSpec(
        image='busybox:1.36',
        command=['sh', '-ec', script],
        args=['pipeline', values, output],
    )


@dsl.pipeline(name='shell-artifact-list-compatibility')
def shell_pipeline():
    with dsl.ParallelFor([1, 2]) as value:
        task = produce(value=value, directory=False)
    shell_consume(values=dsl.Collected(task.outputs['data']))


@dsl.component
def check_imports(values: dsl.Input[List[dsl.Dataset]]) -> int:
    from pathlib import Path

    assert len(values) == 1
    assert 'Kubeflow' in Path(values[0].path).read_text()
    assert values[0].metadata['origin'] == 'public-http'
    return len(values)


@dsl.pipeline(name='imported-artifact-list-compatibility')
def imported_pipeline(uri: str):
    with dsl.ParallelFor([0]):
        item = dsl.importer(
            artifact_uri=uri,
            artifact_class=dsl.Dataset,
            metadata={'origin': 'public-http'},
        )
    check_imports(values=dsl.Collected(item.output))
