# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Raw container outputs: typed values, caching, and producer-side validation
errors that stop the consumer."""

import pytest
from kfp import dsl

from e2e import support


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


@pytest.mark.smoke
def test_typed_outputs_validate_and_cache(client, record):
    for index in range(2):
        submitted, done = support.run_pipeline(
            client, pipeline, {'bad': ''}, timeout=300
        )
        raw = support.workflow(client, done)
        assert done.state == 'SUCCEEDED', support.phases(raw)
        assert (
            support.node_output(support.node(raw, 'check'))
            == 'typed outputs verified'
        )
        if index:
            source = support.node(raw, 'produce')
            assert source.get('memoizationStatus', {}).get('hit') is True, (
                source
            )
            assert not any(
                n.get('displayName') == 'execute' for n in support.nodes(raw)
            )
        record(run_id=submitted.run_id, iteration=index, state=done.state)


@pytest.mark.full
@pytest.mark.parametrize('bad', ['integer', 'boolean', 'items'])
def test_invalid_output_fails_the_producer_not_the_consumer(
    client, record, bad
):
    submitted, done = support.run_pipeline(
        client, pipeline, {'bad': bad}, timeout=300
    )
    raw = support.workflow(client, done)
    assert done.state == 'FAILED', support.phases(raw)
    assert support.node(raw, 'produce')['phase'] == 'Error'
    validation = support.node(raw, 'validate')
    assert validation['phase'] == 'Error', validation
    assert bad in validation.get('message', '').lower(), validation
    assert not any(
        n.get('displayName') == 'check' and n['type'] == 'Pod'
        for n in support.nodes(raw)
    )
    record(run_id=submitted.run_id, bad=bad, state=done.state)
