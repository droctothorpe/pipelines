# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Ordinary SDK code with no native options, images or caching workarounds."""

from kfp import dsl


@dsl.component
def prepare(value: int, dataset: dsl.Output[dsl.Dataset]) -> int:
    from pathlib import Path

    Path(dataset.path).write_text(str(value))
    dataset.metadata['value'] = value
    return value + 1


@dsl.component
def consume(dataset: dsl.Input[dsl.Dataset], expected: int) -> str:
    from pathlib import Path

    assert int(Path(dataset.path).read_text()) + 1 == expected
    assert dataset.metadata['value'] + 1 == expected
    return 'unchanged-sdk-works'


@dsl.pipeline(name='sdk-default-compatibility')
def pipeline(value: int):
    task = prepare(value=value)
    consume(dataset=task.outputs['dataset'], expected=task.outputs['Output'])
