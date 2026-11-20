# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Frozen stock SDK calling conventions, independent of the backend protocol."""

import ast
import importlib
import inspect
import json
from pathlib import Path

import pytest

CONTRACT = json.loads(
    (
        Path(__file__).parent / 'sdk_compatibility' / 'stock_signatures.json'
    ).read_text()
)


def test_top_level_client_alias_is_preserved():
    import kfp
    from kfp.client import Client

    assert kfp.Client is Client


@pytest.mark.parametrize(
    'target,expected',
    CONTRACT['contracts'].items(),
    ids=CONTRACT['contracts'].keys(),
)
def test_stock_public_calling_conventions(target, expected):
    module, attribute = target.split(':')
    current = importlib.import_module(module)
    for name in attribute.split('.'):
        current = getattr(current, name)
    parameters = inspect.signature(current).parameters
    actual_names = list(parameters)
    expected_names = [parameter['name'] for parameter in expected]
    assert [
        name for name in actual_names if name in expected_names
    ] == expected_names, target
    for parameter in expected:
        actual = parameters[parameter['name']]
        assert actual.kind.name == parameter['kind'], (
            target,
            parameter['name'],
        )
        if parameter['default'] is None:
            assert actual.default is inspect.Parameter.empty, (
                target,
                parameter['name'],
            )
        else:
            assert actual.default == ast.literal_eval(parameter['default']), (
                target,
                parameter['name'],
            )
    for name, parameter in parameters.items():
        if name not in expected_names:
            assert (
                parameter.default is not inspect.Parameter.empty
                or parameter.kind
                in (
                    inspect.Parameter.VAR_POSITIONAL,
                    inspect.Parameter.VAR_KEYWORD,
                )
            ), (target, 'new required argument', name)
