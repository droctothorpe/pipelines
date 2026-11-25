# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0

import pytest

from kfp.compiler.argo_commands import arguments

TOKEN = "{{$.inputs.parameters['value']}}"


def test_literal_braces_cannot_close_the_native_expression():
    source = arguments(['quote " {{=malicious}} \\'], {}, {})
    assert '{{' not in source and '}}' not in source
    assert r'\u007b' in source


@pytest.mark.parametrize(
    'value', ['{{$.missing}}' + TOKEN, TOKEN + '{{$.missing}}']
)
def test_unbound_placeholders_are_rejected_on_either_side_of_a_binding(value):
    with pytest.raises(ValueError, match='Unbound KFP placeholder'):
        arguments([value], {TOKEN: '{{inputs.parameters.value}}'}, {})


def test_absent_static_branches_need_no_undeclared_parameter():
    source = arguments(
        [
            {
                'IfPresent': {
                    'InputName': 'value',
                    'Then': [TOKEN],
                    'Else': ['absent'],
                }
            }
        ],
        {},
        {'value': False},
    )
    assert 'absent' in source and '$.inputs' not in source


def test_dynamic_branches_keep_arrays_and_concat_joins_only_its_own_parts():
    source = arguments(
        [
            {'IfPresent': {'InputName': 'value', 'Then': ['--value', TOKEN]}},
            {
                'Concat': [
                    'prefix',
                    {
                        'IfPresent': {
                            'InputName': 'value',
                            'Then': TOKEN,
                            'Else': 'absent',
                        }
                    },
                ]
            },
        ],
        {TOKEN: '{{=fromJSON(inputs.parameters.value)}}'},
        {'value': "inputs.parameters.value != 'null'"},
    )
    assert "inputs.parameters.value != 'null' ?" in source
    assert ' : []' in source
    assert 'sprig.join' in source
    assert '{{' not in source
