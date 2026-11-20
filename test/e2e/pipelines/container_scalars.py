# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Raw container outputs with typed values and a deliberate validation
error."""

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
