// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import { argoRequest } from './Argo';
import { createResource, type NativeResource } from './ArgoResources';
import type { TriggerSchedule } from './TriggerUtils';
import { prepareArtifactLists } from './NativeArtifactLists';

export const SCHEDULE_CONFIG = 'pipelines.kubeflow.org/schedule-config';
export interface ScheduleSettings {
  trigger?: TriggerSchedule;
  catchup: boolean;
  maxConcurrentRuns?: string;
}

export function scheduleSettings(settings: ScheduleSettings) {
  const periodic = settings.trigger?.periodic_schedule;
  const cron = settings.trigger?.cron_schedule;
  if (!!periodic === !!cron) throw new Error('Exactly one recurring-run trigger is required.');
  const limit = Number(settings.maxConcurrentRuns ?? '10');
  if (!Number.isSafeInteger(limit) || limit < 1)
    throw new Error('Maximum concurrency must be a positive integer.');
  let expression: string;
  let timezone = 'UTC';
  if (periodic) {
    const seconds = Number(periodic.interval_second);
    if (!Number.isSafeInteger(seconds) || seconds < 1)
      throw new Error('The interval must be a positive integer.');
    expression = `@every ${seconds}s`;
  } else {
    expression = cron?.cron?.trim() || '';
    const match = /^(?:CRON_TZ|TZ)=(\S+)\s+(.+)$/.exec(expression);
    if (match) [, timezone, expression] = match;
    const fields = expression.split(/\s+/);
    if (fields.length === 6 && fields[0] === '0') expression = fields.slice(1).join(' ');
    expression = expression.replace(/\?/g, '*');
    if (!expression) throw new Error('A cron expression is required.');
  }
  const value = periodic || cron!;
  const start = value.start_time && new Date(value.start_time);
  const end = value.end_time && new Date(value.end_time);
  if ((start && !Number.isFinite(+start)) || (end && !Number.isFinite(+end)))
    throw new Error('Invalid schedule date.');
  if (start && end && end < start) throw new Error('End time must not precede start time.');
  const spec: Record<string, any> = {
    schedules: [expression],
    timezone,
    suspend: false,
    concurrencyPolicy: limit === 1 ? 'Forbid' : 'Allow',
    startingDeadlineSeconds: settings.catchup ? 2147483647 : 0,
  };
  const conditions = [];
  if (start) conditions.push(`now().Unix() >= ${Math.floor(+start / 1000)}`);
  if (end) {
    conditions.push(`now().Unix() <= ${Math.floor(+end / 1000)}`);
    spec.stopStrategy = { expression: `now().Unix() > ${Math.floor(+end / 1000)}` };
  }
  if (conditions.length) spec.when = '{{= ' + conditions.join(' && ') + ' }}';
  const configuration = {
    max_concurrency: limit,
    no_catchup: !settings.catchup,
    trigger: {
      kind: periodic ? 'periodic' : 'cron',
      interval_second: periodic?.interval_second ?? null,
      cron: cron?.cron ?? null,
      start_time: start?.toISOString() ?? null,
      end_time: end?.toISOString() ?? null,
    },
  };
  return { spec, configuration };
}

export function scheduleTrigger(schedule?: NativeResource): ScheduleSettings {
  if (!schedule) return { catchup: true, maxConcurrentRuns: '10' };
  const encoded = schedule.metadata.annotations?.[SCHEDULE_CONFIG];
  const configuration = encoded ? JSON.parse(encoded) : {};
  let expression = schedule.spec?.schedules?.[0] || schedule.spec?.schedule || '';
  const interval = /^@every (\d+)s$/.exec(expression);
  if (schedule.spec?.timezone && schedule.spec.timezone !== 'UTC')
    expression = `TZ=${schedule.spec.timezone} ${expression}`;
  const trigger =
    configuration.trigger ||
    (interval
      ? { kind: 'periodic', interval_second: interval[1] }
      : { kind: 'cron', cron: expression });
  const dates = {
    start_time: trigger.start_time ? new Date(trigger.start_time) : undefined,
    end_time: trigger.end_time ? new Date(trigger.end_time) : undefined,
  };
  return {
    catchup:
      configuration.no_catchup !== undefined
        ? !configuration.no_catchup
        : !!schedule.spec?.startingDeadlineSeconds,
    maxConcurrentRuns: String(
      configuration.max_concurrency ?? (schedule.spec?.concurrencyPolicy === 'Forbid' ? 1 : 10),
    ),
    trigger:
      trigger.kind === 'periodic'
        ? { periodic_schedule: { ...dates, interval_second: String(trigger.interval_second) } }
        : { cron_schedule: { ...dates, cron: trigger.cron } },
  };
}

export async function createSchedule(
  namespace: string,
  resource: NativeResource,
  settings: ScheduleSettings,
) {
  const { spec, configuration } = scheduleSettings(settings);
  const schedule = structuredClone(resource);
  schedule.metadata.annotations = {
    ...schedule.metadata.annotations,
    [SCHEDULE_CONFIG]: JSON.stringify(configuration),
  };
  schedule.spec = { ...schedule.spec, ...spec };
  schedule.spec.workflowSpec = await prepareArtifactLists(namespace, schedule.spec.workflowSpec);
  let semaphore: NativeResource | undefined;
  if (configuration.max_concurrency > 1) {
    semaphore = await createResource(namespace, 'schedule-limits', {
      apiVersion: 'v1',
      kind: 'ConfigMap',
      metadata: {
        name: schedule.metadata.name + '-limit',
        namespace,
        labels: { 'pipelines.kubeflow.org/resource': 'schedule-limit' },
      },
      data: { limit: String(configuration.max_concurrency) },
    });
    const workflow = schedule.spec.workflowSpec;
    workflow.synchronization ||= {};
    workflow.synchronization.semaphores ||= [];
    workflow.synchronization.semaphores.push({
      configMapKeyRef: { name: semaphore!.metadata.name, key: 'limit' },
    });
  }
  try {
    return await createResource(namespace, 'cron-workflows', schedule);
  } catch (error) {
    if (semaphore?.metadata.uid)
      await argoRequest(
        `/kubernetes/api/v1/namespaces/${encodeURIComponent(namespace)}/configmaps/${encodeURIComponent(semaphore.metadata.name)}`,
        undefined,
        {
          method: 'DELETE',
          body: JSON.stringify({
            apiVersion: 'v1',
            kind: 'DeleteOptions',
            preconditions: { uid: semaphore.metadata.uid },
          }),
        },
      );
    throw error;
  }
}
