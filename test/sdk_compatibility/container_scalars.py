# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Raw container outputs: types, metadata, caching, and producer-side errors."""

import json
import os
from uuid import uuid4

import kfp
from kfp import dsl


@dsl.container_component
def produce(
    bad: str,
    integer: dsl.OutputPath(int),
    floating: dsl.OutputPath(float),
    boolean: dsl.OutputPath(bool),
    items: dsl.OutputPath(list),
    mapping: dsl.OutputPath(dict),
    data: dsl.Output[dsl.Dataset],
):
    return dsl.ContainerSpec(
        image='python:3.11',
        command=['python3', '-c'],
        args=[
            'import pathlib,sys; bad=sys.argv[1]; values=[" +003\\n", " 2.5e1\\n", "True\\n", "[1,2,3]", \'{"key":7}\', "payload"]; '
            'names=["integer","floating","boolean","items","mapping","data"]; '
            '[pathlib.Path(path).write_text("invalid" if bad==name else value) for name,value,path in zip(names,values,sys.argv[2:])]',
            bad,
            integer,
            floating,
            boolean,
            items,
            mapping,
            data.path,
        ],
    )


@dsl.component
def check(
    integer: int,
    floating: float,
    boolean: bool,
    items: list,
    mapping: dict,
    data: dsl.Input[dsl.Dataset],
) -> str:
    from pathlib import Path

    assert integer == 3 and type(integer) is int
    # Stock protobuf JSON also serializes integral doubles without a decimal point.
    assert floating == 25.0
    assert boolean is True
    assert items == [1, 2, 3]
    assert mapping == {'key': 7}
    assert Path(data.path).read_text() == 'payload'
    return 'typed outputs verified'


@dsl.pipeline(name='raw-container-scalar-compatibility')
def pipeline(bad: str = ''):
    source = produce(bad=bad)
    check(
        integer=source.outputs['integer'],
        floating=source.outputs['floating'],
        boolean=source.outputs['boolean'],
        items=source.outputs['items'],
        mapping=source.outputs['mapping'],
        data=source.outputs['data'],
    )


if __name__ == '__main__':
    namespace = os.environ.get('KFP_TEST_NAMESPACE', 'kfp-argo')
    client = kfp.Client(
        host=os.environ.get('KFP_TEST_HOST', 'http://127.0.0.1:3003'),
        namespace=namespace,
        existing_token=os.environ['KFP_TEST_TOKEN'],
    )
    report = []
    for index, bad in enumerate(['', '', 'integer', 'boolean', 'items']):
        run = client.create_run_from_pipeline_func(
            pipeline,
            arguments={'bad': bad},
            run_name='Raw outputs compatibility ' + uuid4().hex[:8],
            experiment_name='SDK backwards compatibility',
            namespace=namespace,
        )
        complete = run.wait_for_run_completion(timeout=180)
        raw = client._run_api.transport.request(
            'GET',
            f'/argo/api/v1/workflows/{namespace}/{complete.pipeline_spec["metadata"]["name"]}',
        )
        nodes = list(raw['status']['nodes'].values())
        source = next(
            node for node in nodes if node.get('displayName') == 'produce'
        )
        if bad:
            assert complete.state == 'FAILED', [
                (n.get('displayName'), n['phase'], n.get('message'))
                for n in nodes
            ]
            assert source['phase'] == 'Error', source
            validation = next(
                node for node in nodes if node.get('displayName') == 'validate'
            )
            assert validation['phase'] == 'Error', validation
            assert bad in validation.get('message', '').lower(), validation
            assert not any(
                node.get('displayName') == 'check' and node['type'] == 'Pod'
                for node in nodes
            ), nodes
        else:
            assert complete.state == 'SUCCEEDED', [
                (n.get('displayName'), n['phase'], n.get('message'))
                for n in nodes
            ]
            consumer = next(
                node for node in nodes if node.get('displayName') == 'check'
            )
            assert (
                next(
                    p['value']
                    for p in consumer['outputs']['parameters']
                    if p['name'] == 'Output'
                )
                == 'typed outputs verified'
            )
            if index == 1:
                assert source.get('memoizationStatus', {}).get('hit') is True, (
                    source
                )
                assert not any(
                    node.get('displayName') == 'execute' for node in nodes
                ), nodes
        report.append(
            {
                'run_id': run.run_id,
                'bad': bad,
                'state': complete.state,
                'producer_phase': source['phase'],
            }
        )
    print(json.dumps(report, indent=2))
