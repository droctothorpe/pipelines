# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Stock listing semantics over the native inventory (C39)."""

import datetime

import pytest
from kfp import server_api as models
from kfp.client import _listing


def _run(name, created, state='SUCCEEDED', description=''):
    return models.V2Run(
        run_id=f'id-{name}',
        display_name=name,
        description=description,
        state=state,
        created_at=datetime.datetime(
            2026, 1, created, tzinfo=datetime.timezone.utc
        ),
    )


RUNS = [_run('Bravo', 2), _run('alpha', 1, state='FAILED'), _run('Charlie', 3)]


def _names(result):
    return [run.display_name for run in result[0]]


def test_default_order_is_creation_time_ascending():
    assert _names(_listing.page(RUNS, scope='runs')) == [
        'alpha',
        'Bravo',
        'Charlie',
    ]
    assert _names(
        _listing.page(RUNS, scope='runs', sort_by='created_at desc')
    ) == [
        'Charlie',
        'Bravo',
        'alpha',
    ]


def test_sort_fields_and_legacy_aliases_are_case_insensitive():
    assert _names(_listing.page(RUNS, scope='runs', sort_by='Name')) == [
        'alpha',
        'Bravo',
        'Charlie',
    ]
    assert _names(
        _listing.page(RUNS, scope='runs', sort_by='display_name DESC')
    ) == [
        'Charlie',
        'Bravo',
        'alpha',
    ]


@pytest.mark.parametrize(
    'filter_json, expected',
    [
        (
            '{"predicates":[{"key":"name","operation":"EQUALS","string_value":"bravo"}]}',
            ['Bravo'],
        ),
        (
            '{"predicates":[{"key":"display_name","operation":"IS_SUBSTRING","string_value":"ARL"}]}',
            ['Charlie'],
        ),
        (
            '{"predicates":[{"key":"status","operation":"EQUALS","string_value":"FAILED"}]}',
            ['alpha'],
        ),
        (
            '{"predicates":[{"key":"id","operation":"EQUALS","string_value":"id-Bravo"}]}',
            ['Bravo'],
        ),
        (
            '{"predicates":[{"key":"name","operation":"IN","string_values":{"values":["ALPHA","charlie"]}}]}',
            ['alpha', 'Charlie'],
        ),
    ],
    ids=[
        'name-alias-folded',
        'substring-folded',
        'status-alias',
        'id-alias',
        'in-folded',
    ],
)
def test_filters_accept_stock_aliases_and_fold_case(filter_json, expected):
    assert (
        _names(_listing.page(RUNS, scope='runs', filter=filter_json))
        == expected
    )


def test_unknown_filter_field_is_still_rejected():
    with pytest.raises(models.ApiException) as error:
        _listing.page(
            RUNS,
            scope='runs',
            filter='{"predicates":[{"key":"colour","operation":"EQUALS","string_value":"x"}]}',
        )
    assert error.value.status == 400


def test_page_size_defaults_and_cap_match_stock():
    many = [_run(f'r{index:03d}', 1) for index in range(250)]
    page, total, token = _listing.page(many, scope='runs', page_size=0)
    assert (len(page), total, bool(token)) == (20, 250, True)
    page, _, _ = _listing.page(many, scope='runs', page_size=1000)
    assert len(page) == 200
