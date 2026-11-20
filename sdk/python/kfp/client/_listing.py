# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Public SDK filtering and opaque pagination over native resource inventories."""

import base64
import datetime
import hashlib
import json
from urllib.parse import unquote

from kfp.server_api import ApiException

OPERATIONS = {
    1: 'EQUALS',
    2: 'NOT_EQUALS',
    3: 'GREATER_THAN',
    5: 'GREATER_THAN_EQUALS',
    6: 'LESS_THAN',
    7: 'LESS_THAN_EQUALS',
    8: 'IN',
    9: 'IS_SUBSTRING',
}


def _scalar(value):
    if isinstance(value, datetime.datetime):
        return value.isoformat()
    return value


def _matches(item, predicate):
    key = predicate.get('key')
    if key not in item.openapi_types:
        raise ApiException(status=400, reason=f'Unknown filter field: {key}')
    value = _scalar(getattr(item, key, None))
    operation = predicate.get('operation')
    operation = OPERATIONS.get(operation, operation)
    provided = [
        candidate
        for candidate in (
            'string_value',
            'stringValue',
            'int_value',
            'intValue',
            'long_value',
            'longValue',
            'timestamp_value',
            'timestampValue',
            'string_values',
            'stringValues',
            'int_values',
            'intValues',
            'long_values',
            'longValues',
        )
        if candidate in predicate
    ]
    if len(provided) != 1:
        raise ApiException(
            status=400,
            reason='A filter predicate must contain exactly one value.',
        )
    expected = predicate[provided[0]]
    if operation == 'IN':
        if isinstance(expected, dict):
            expected = expected.get('values', [])
        if not isinstance(expected, list):
            raise ApiException(
                status=400, reason='IN requires a list of values.'
            )
        return value in expected
    if operation == 'EQUALS':
        return value == expected
    if operation == 'NOT_EQUALS':
        return value != expected
    if operation == 'IS_SUBSTRING':
        return (
            isinstance(value, str)
            and isinstance(expected, str)
            and expected in value
        )
    if value is None:
        return False
    try:
        if operation == 'GREATER_THAN':
            return value > expected
        if operation == 'GREATER_THAN_EQUALS':
            return value >= expected
        if operation == 'LESS_THAN':
            return value < expected
        if operation == 'LESS_THAN_EQUALS':
            return value <= expected
    except TypeError as error:
        raise ApiException(
            status=400, reason='Filter value has the wrong type.'
        ) from error
    raise ApiException(
        status=400, reason=f'Unknown filter operation: {operation}'
    )


def page(items, *, scope, page_token='', page_size=10, sort_by='', filter=None):
    if (
        isinstance(page_size, bool)
        or not isinstance(page_size, int)
        or page_size < 0
    ):
        raise ApiException(
            status=400, reason='page_size must be a non-negative integer.'
        )
    page_size = page_size or 10
    try:
        predicates = json.loads(unquote(filter))['predicates'] if filter else []
        if not isinstance(predicates, list):
            raise ValueError('predicates must be a list')
    except (ValueError, KeyError, TypeError) as error:
        raise ApiException(status=400, reason='Invalid filter JSON.') from error
    # Validate filter syntax even when the inventory is empty where possible.
    if any(not isinstance(predicate, dict) for predicate in predicates):
        raise ApiException(
            status=400, reason='Filter predicates must be objects.'
        )
    values = [
        item
        for item in items
        if all(_matches(item, predicate) for predicate in predicates)
    ]
    fields = [
        part.strip().split()
        for part in (sort_by or 'created_at desc').split(',')
    ]
    for field in reversed(fields):
        if (
            not field
            or len(field) > 2
            or (len(field) == 2 and field[1].lower() not in ('asc', 'desc'))
        ):
            raise ApiException(status=400, reason='Invalid sort_by expression.')
        name = field[0]
        if values and name not in values[0].openapi_types:
            raise ApiException(status=400, reason=f'Unknown sort field: {name}')
        values.sort(
            key=lambda item: (
                getattr(item, name, None) is not None,
                _scalar(getattr(item, name, None)) or '',
            ),
            reverse=len(field) == 2 and field[1].lower() == 'desc',
        )
    identity = hashlib.sha256(
        json.dumps([scope, sort_by, filter], sort_keys=True).encode()
    ).hexdigest()
    offset = 0
    if page_token:
        try:
            token = json.loads(base64.urlsafe_b64decode(page_token.encode()))
            offset = token['offset']
            if (
                token['query'] != identity
                or type(offset) is not int
                or offset < 0
            ):
                raise ValueError('Token does not belong to this query')
        except (ValueError, KeyError, TypeError) as error:
            raise ApiException(
                status=400, reason='Invalid page token for this query.'
            ) from error
    next_token = ''
    if offset + page_size < len(values):
        next_token = base64.urlsafe_b64encode(
            json.dumps(
                {'query': identity, 'offset': offset + page_size}
            ).encode()
        ).decode()
    return values[offset : offset + page_size], len(values), next_token
