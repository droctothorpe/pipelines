# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Translate public recurring-run settings to unmodified Argo CronWorkflows."""

import datetime
import re

from kfp import server_api as models

# A long, duration-safe window avoids imposing a new short retention cutoff.
# Argo still recovers at most one missed occurrence, an accepted contract exception.
CATCHUP_WINDOW_SECONDS = 2_147_483_647
SCHEDULE_CONFIG = 'pipelines.kubeflow.org/schedule-config'


def date(value):
    if value is None:
        return None
    try:
        parsed = (
            value
            if isinstance(value, datetime.datetime)
            else datetime.datetime.fromisoformat(value.replace('Z', '+00:00'))
        )
        if parsed.tzinfo is None:
            raise ValueError('timezone is required')
        return parsed
    except (TypeError, ValueError, AttributeError) as error:
        raise models.ApiException(
            status=400,
            reason='Schedule timestamps must be RFC3339 dates with a timezone.',
        ) from error


def positive_integer(value, name):
    # Int64 fields are returned as strings by the stock SDK response models.
    if isinstance(value, str) and re.fullmatch(r'[0-9]+', value):
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise models.ApiException(
            status=400, reason=f'{name} must be a positive integer.'
        )
    return value


def cron_schedule(expression):
    if not isinstance(expression, str) or not expression.strip():
        raise models.ApiException(
            status=400, reason='cron_expression is required.'
        )
    expression = expression.strip()
    timezone = 'UTC'
    match = re.match(r'^(?:CRON_TZ|TZ)=(\S+)\s+(.+)$', expression)
    if match:
        timezone, expression = match.groups()
    fields = expression.split()
    if len(fields) == 6 and fields[0] == '0':
        fields = fields[1:]
    return ' '.join(
        '*' if field == '?' else field for field in fields
    ), timezone


def settings(recurring_run):
    trigger = recurring_run.trigger
    periodic = trigger.periodic_schedule if trigger else None
    cron = trigger.cron_schedule if trigger else None
    if bool(periodic) == bool(cron):
        raise models.ApiException(
            status=400, reason='Exactly one recurring-run trigger is required.'
        )
    timezone = 'UTC'
    if periodic:
        interval = positive_integer(periodic.interval_second, 'interval_second')
        expression = f'@every {interval}s'
    else:
        expression, timezone = cron_schedule(cron.cron)
    configuration = periodic or cron
    start, end = date(configuration.start_time), date(configuration.end_time)
    if start and end and end < start:
        raise models.ApiException(
            status=400, reason='end_time must not precede start_time.'
        )
    limit = (
        recurring_run.max_concurrency
        if recurring_run.max_concurrency is not None
        else 1
    )
    limit = positive_integer(limit, 'max_concurrency')
    spec = {
        'schedules': [expression],
        'timezone': timezone,
        'suspend': recurring_run.mode != models.RecurringRunMode.ENABLE,
        'concurrencyPolicy': 'Forbid' if limit == 1 else 'Allow',
        'startingDeadlineSeconds': 0
        if recurring_run.no_catchup
        else CATCHUP_WINDOW_SECONDS,
    }
    conditions = []
    if start:
        conditions.append(f'now().Unix() >= {int(start.timestamp())}')
    if end:
        conditions.append(f'now().Unix() <= {int(end.timestamp())}')
        spec['stopStrategy'] = {
            'expression': f'now().Unix() > {int(end.timestamp())}'
        }
    if conditions:
        spec['when'] = '{{= ' + ' && '.join(conditions) + ' }}'
    data = {
        'max_concurrency': limit,
        'no_catchup': bool(recurring_run.no_catchup),
        'trigger': {
            'kind': 'periodic' if periodic else 'cron',
            'interval_second': periodic.interval_second if periodic else None,
            'cron': cron.cron if cron else None,
            'start_time': start.isoformat() if start else None,
            'end_time': end.isoformat() if end else None,
        },
    }
    return spec, data


def trigger_from_config(configuration):
    trigger = configuration.get('trigger', {})
    arguments = {
        'start_time': date(trigger.get('start_time')),
        'end_time': date(trigger.get('end_time')),
    }
    if trigger.get('kind') == 'periodic':
        return models.V2Trigger(
            periodic_schedule=models.V2PeriodicSchedule(
                interval_second=str(trigger['interval_second']), **arguments
            )
        )
    return models.V2Trigger(
        cron_schedule=models.V2CronSchedule(
            cron=trigger.get('cron'), **arguments
        )
    )
