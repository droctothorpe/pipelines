# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Dynamic artifact lists: cached files/directories, empty lists and credential isolation."""

import json
import os
import time
from typing import List
from uuid import uuid4

import kfp
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
        assert value.uri.startswith('s3://argo-artifacts/')
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
    with dsl.If(directory == True):
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


def verify_iteration(client):
    report = []
    for function, arguments in [
        (iteration_pipeline, {'values': [1, 2]}),
        (iteration_pipeline, {'values': []}),
        (
            nested_iteration_pipeline,
            {'values': [3, 4], 'expected': [3, 3, 4, 4]},
        ),
    ]:
        run = client.create_run_from_pipeline_func(
            function,
            arguments=arguments,
            run_name='Artifact iteration ' + uuid4().hex[:8],
            experiment_name='SDK backwards compatibility',
            namespace=client.get_user_namespace(),
        )
        done = run.wait_for_run_completion(timeout=240)
        assert done.state == 'SUCCEEDED', [
            (t.display_name, t.state, t.lifecycle_message)
            for t in (done.tasks or [])
            if t.state == 'FAILED'
        ]
        task = next(t for t in done.tasks if t.display_name == 'check-numbers')
        assert next(
            p.value
            for p in task.outputs.parameters
            if p.parameter_key == 'Output'
        ) == sum(arguments.get('expected', arguments['values']))
        report.append(
            {
                'run_id': run.run_id,
                'pipeline': function.name,
                'state': done.state,
            }
        )
    return report


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


def verify_raw_lists(client):
    report = []
    namespace = client.get_user_namespace()
    for values, directory in [([1, 2], False), ([1, 2], True), ([], False)]:
        run = client.create_run_from_pipeline_func(
            raw_pipeline,
            arguments={
                'values': values,
                'directory': directory,
                'nonce': uuid4().hex,
            },
            run_name='Raw artifact list ' + uuid4().hex[:8],
            experiment_name='SDK backwards compatibility',
            namespace=namespace,
        )
        done = run.wait_for_run_completion(timeout=240)
        assert done.state == 'SUCCEEDED', [
            (t.display_name, t.state, t.lifecycle_message)
            for t in (done.tasks or [])
        ]
        task = next(t for t in done.tasks if t.display_name == 'raw-consume')
        assert next(
            p.value
            for p in task.outputs.parameters
            if p.parameter_key == 'total'
        ) == sum(values)
        report.append(
            {
                'run_id': run.run_id,
                'values': values,
                'directory': directory,
                'state': done.state,
            }
        )
    run = client.create_run_from_pipeline_func(
        shell_pipeline,
        arguments={},
        run_name='Shell artifact list ' + uuid4().hex[:8],
        experiment_name='SDK backwards compatibility',
        namespace=namespace,
    )
    done = run.wait_for_run_completion(timeout=240)
    assert done.state == 'SUCCEEDED', [
        (t.display_name, t.state, t.lifecycle_message)
        for t in (done.tasks or [])
    ]
    task = next(t for t in done.tasks if t.display_name == 'shell-consume')
    assert (
        next(
            p.value
            for p in task.outputs.parameters
            if p.parameter_key == 'output'
        )
        == 'shell-verified'
    )
    report.append(
        {'run_id': run.run_id, 'image': 'busybox:1.36', 'state': done.state}
    )
    return report


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


def verify_imports(client):
    namespace = client.get_user_namespace()
    report = []
    for uri, succeeds in [
        (
            'https://raw.githubusercontent.com/kubeflow/pipelines/7780f12acfbde9f16169c7fcbfdfb6c3ef5432ea/README.md',
            True,
        ),
        ('s3://argo-artifacts/missing-artifact-list-' + uuid4().hex, False),
    ]:
        run = client.create_run_from_pipeline_func(
            imported_pipeline,
            arguments={'uri': uri},
            run_name='Imported list ' + uuid4().hex[:8],
            experiment_name='SDK backwards compatibility',
            namespace=namespace,
        )
        complete = run.wait_for_run_completion(timeout=180)
        raw = client._run_api.transport.request(
            'GET',
            f'/argo/api/v1/workflows/{namespace}/{complete.pipeline_spec["metadata"]["name"]}',
        )
        nodes = list(raw['status']['nodes'].values())
        assert complete.state == ('SUCCEEDED' if succeeds else 'FAILED'), [
            (n.get('displayName'), n.get('phase'), n.get('message'))
            for n in nodes
        ]
        if not succeeds:
            consumer = next(
                n for n in nodes if n.get('displayName') == 'check-imports'
            )
            assert 'kfp-stage-artifacts' in consumer.get('message', ''), (
                consumer
            )
        report.append(
            {
                'run_id': run.run_id,
                'expected_success': succeeds,
                'state': complete.state,
            }
        )
    return report


if __name__ == '__main__':
    namespace = os.environ.get('KFP_TEST_NAMESPACE', 'kfp-argo')
    client = kfp.Client(
        host=os.environ.get('KFP_TEST_HOST', 'http://127.0.0.1:3003'),
        namespace=namespace,
        existing_token=os.environ['KFP_TEST_TOKEN'],
    )
    report = []
    cases = [
        (pipeline, [1, 2], False),
        (pipeline, [1, 2], False),
        (pipeline, [1, 2], True),
        (pipeline, [], False),
        (nested_pipeline, [3, 4], True),
        (pipeline, [1] * 256, False),
    ]
    for index, (function, values, directory) in enumerate(cases):
        expected = (
            [v for v in values for _ in range(2)]
            if function is nested_pipeline
            else values
        )
        arguments = {
            'values': values,
            'directory': directory,
            'nonce': uuid4().hex,
        }
        if function is nested_pipeline:
            arguments['expected'] = expected
        run = client.create_run_from_pipeline_func(
            function,
            arguments=arguments,
            run_name='Artifact-list compatibility ' + uuid4().hex[:8],
            experiment_name='SDK backwards compatibility',
            namespace=namespace,
        )
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            complete = client.get_run(run.run_id)
            raw = client._run_api.transport.request(
                'GET',
                f'/argo/api/v1/workflows/{namespace}/{complete.pipeline_spec["metadata"]["name"]}',
            )
            nodes = list(raw.get('status', {}).get('nodes', {}).values())
            if complete.state in ('SUCCEEDED', 'FAILED', 'CANCELED'):
                break
            if any(n.get('phase') == 'Error' for n in nodes):
                client.terminate_run(run.run_id)
                raise AssertionError(
                    [
                        (n.get('displayName'), n.get('phase'), n.get('message'))
                        for n in nodes
                    ]
                )
            time.sleep(3)
        assert complete.state == 'SUCCEEDED', [
            (n.get('displayName'), n.get('phase'), n.get('message'))
            for n in nodes
        ]
        consumer = next(n for n in nodes if n.get('displayName') == 'consume')
        assert next(
            p['value']
            for p in consumer['outputs']['parameters']
            if p['name'] == 'Output'
        ) == str(sum(expected))
        pods = client._run_api.transport.collection(
            f'/kubernetes/api/v1/namespaces/{namespace}/pods',
            params={
                'labelSelector': 'workflows.argoproj.io/workflow='
                + raw['metadata']['name']
            },
            kubernetes=True,
        )
        pod = next(
            p
            for p in pods
            if any(
                c['name'] == 'kfp-stage-artifacts'
                for c in p['spec'].get('initContainers', [])
            )
        )
        main = next(c for c in pod['spec']['containers'] if c['name'] == 'main')
        stage = next(
            c
            for c in pod['spec']['initContainers']
            if c['name'] == 'kfp-stage-artifacts'
        )
        secret_volumes = {
            v['name'] for v in pod['spec']['volumes'] if 'secret' in v
        }
        assert not any(
            m['name'] in secret_volumes for m in main['volumeMounts']
        ), 'Storage secrets must not be mounted in main'
        assert any(
            m['name'] in secret_volumes and m.get('readOnly')
            for m in stage['volumeMounts']
        )
        if index == 1:
            assert len(pods) == 1, (
                'Cached producers create no pods; only the consumer is new'
            )
            assert all(
                n.get('memoizationStatus', {}).get('hit')
                for n in nodes
                if n.get('displayName') == 'produce'
            )
        report.append(
            {
                'run_id': run.run_id,
                'values': values
                if len(values) < 20
                else f'{len(values)} repeated values',
                'directory': directory,
                'pods': len(pods),
                'pipeline': function.name,
            }
        )
    report.extend(verify_imports(client))
    print(json.dumps(report, indent=2))
