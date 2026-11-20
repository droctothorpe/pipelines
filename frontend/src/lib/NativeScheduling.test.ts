// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import { afterEach, expect, it, vi } from 'vitest';
import { createSchedule, scheduleSettings, scheduleTrigger } from './NativeScheduling';
afterEach(() => vi.unstubAllGlobals());
import { parseTrigger, PeriodicInterval } from './TriggerUtils';

it('preserves SDK intervals, date bounds, concurrency and catch-up through UI cloning', () => {
  const settings = {
    trigger: {
      periodic_schedule: {
        interval_second: '7',
        start_time: new Date('2027-01-01T10:00:00Z'),
        end_time: new Date('2027-01-01T11:00:00Z'),
      },
    },
    catchup: true,
    maxConcurrentRuns: '3',
  };
  const result = scheduleSettings(settings);
  expect(result.spec.schedules).toEqual(['@every 7s']);
  expect(result.spec.suspend).toBe(false);
  expect(result.spec.concurrencyPolicy).toBe('Allow');
  expect(result.spec.startingDeadlineSeconds).toBe(2147483647);
  expect(result.spec.when).toContain('now().Unix() >= 1798797600');
  expect(result.spec.stopStrategy.expression).toBe('now().Unix() > 1798801200');
  const restored = scheduleTrigger({
    apiVersion: 'argoproj.io/v1alpha1',
    kind: 'CronWorkflow',
    metadata: {
      name: 'sdk-schedule',
      annotations: {
        'pipelines.kubeflow.org/schedule-config': JSON.stringify(result.configuration),
      },
    },
    spec: result.spec,
  });
  expect(restored).toEqual(settings);
  expect(parseTrigger(restored.trigger!).intervalCategory).toBe(PeriodicInterval.SECOND);
});

it('lowers stock minute-resolution six-field cron expressions and preserves timezone', () => {
  const result = scheduleSettings({
    trigger: { cron_schedule: { cron: 'TZ=Europe/Paris 0 15 9 * * ?' } },
    catchup: false,
    maxConcurrentRuns: '1',
  });
  expect(result.spec.schedules).toEqual(['15 9 * * *']);
  expect(result.spec.timezone).toBe('Europe/Paris');
  expect(result.spec.concurrencyPolicy).toBe('Forbid');
  expect(result.spec.startingDeadlineSeconds).toBe(0);
});

it('keeps existing locks and cleans up only its semaphore when schedule creation fails', async () => {
  const requests: Array<{ url: string; options?: RequestInit }> = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url, options) => {
      requests.push({ url: String(url), options });
      if (options?.method === 'POST' && String(url).endsWith('/configmaps')) {
        return new Response(
          JSON.stringify({
            ...JSON.parse(options.body),
            metadata: { name: 'schedule-limit', uid: 'owned-uid' },
          }),
        );
      }
      if (options?.method === 'POST') return new Response('{}', { status: 400 });
      return new Response('{}');
    }),
  );
  await expect(
    createSchedule(
      'team',
      {
        apiVersion: 'argoproj.io/v1alpha1',
        kind: 'CronWorkflow',
        metadata: { name: 'schedule' },
        spec: {
          workflowSpec: {
            synchronization: {
              semaphores: [{ configMapKeyRef: { name: 'existing', key: 'limit' } }],
            },
          },
        },
      },
      {
        trigger: { periodic_schedule: { interval_second: '60' } },
        maxConcurrentRuns: '10',
        catchup: true,
      },
    ),
  ).rejects.toThrow('400');
  const submitted = JSON.parse(requests[1].options!.body as string).cronWorkflow;
  expect(submitted.spec.workflowSpec.synchronization.semaphores).toHaveLength(2);
  expect(submitted.spec.workflowSpec.synchronization.semaphores[0].configMapKeyRef.name).toBe(
    'existing',
  );
  expect(requests[2].options?.method).toBe('DELETE');
  expect(JSON.parse(requests[2].options!.body as string).preconditions).toEqual({
    uid: 'owned-uid',
  });
});

it('rejects invalid intervals and limits before a request', () => {
  expect(() =>
    scheduleSettings({
      trigger: { periodic_schedule: { interval_second: '0' } },
      catchup: true,
      maxConcurrentRuns: '1',
    }),
  ).toThrow('interval');
  expect(() =>
    scheduleSettings({
      trigger: { periodic_schedule: { interval_second: '60' } },
      catchup: true,
      maxConcurrentRuns: '1.5',
    }),
  ).toThrow('concurrency');
});
