# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Optional values across pipeline and condition boundaries, for Python
components."""

from typing import Optional

from kfp import dsl
from kfp.dsl import Artifact, Input


@dsl.component
def check(expected: str, value: str = None) -> str:
    import json

    actual = json.dumps(value)
    assert actual == expected, (actual, expected)
    return actual


@dsl.component
def fallback(value: str = 'fallback') -> str:
    return value


@dsl.component
def interpolation(value: str, original: str) -> str:
    assert value == 'prefix:' + original, (value, original)
    return value


@dsl.pipeline
def forwarded(expected: str, value: str = None) -> str:
    check(expected=expected, value=value)
    return value


@dsl.pipeline(name='optional-input-compatibility')
def pipeline(expected: str = 'null', value: str = None):
    result = forwarded(expected=expected, value=value)
    check(expected=expected, value=result.output)
    fallback(value=value)
    with dsl.If(value == None):  # noqa: E711
        missing = forwarded(expected='null')
    with dsl.Else():
        present = fallback(value=value)
        check(expected=expected, value=value)
        interpolation(value=f'prefix:{value}', original=value)
    check(expected=expected, value=dsl.OneOf(missing.output, present.output))


@dsl.component
def describe(model: Optional[Input[Artifact]] = None) -> str:
    return 'absent' if model is None else model.uri


@dsl.pipeline(name='optional-root-artifact-compatibility')
def root_artifact_pipeline(model: Optional[Input[Artifact]] = None):
    """L02: an optional root artifact input is absent at run time, as in
    stock, whose run API carried no artifact values."""
    describe(model=model)
