// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import { V2RuntimeState, type TaskTimingView } from './NativeViewTypes';

export function sanitizeExternalHref(url?: string): string | undefined {
  if (!url) return undefined;
  try {
    const parsed = new URL(url);
    if (['http:', 'https:'].includes(parsed.protocol)) return url;
  } catch {
    /* Invalid external URL. */
  }
  return undefined;
}

export const logger = {
  error: console.error,
  warn: console.warn,
  info: console.info,
  verbose: console.debug,
};
export const formatDateString = (date: Date | string | undefined) =>
  typeof date === 'string' ? new Date(date).toLocaleString() : date ? date.toLocaleString() : '-';
export const hasFinishedV2 = (state?: string) =>
  ['SUCCEEDED', 'FAILED', 'CANCELED', 'SKIPPED'].includes(state || '');
export const isTaskFinished = (state?: string) => state === 'CACHED' || hasFinishedV2(state);
export const getTaskDisplayName = (task: TaskTimingView) =>
  task.display_name || task.name || task.task_id || 'Unknown task';
export const checkIfTerminatedV2 = (state?: V2RuntimeState, message?: string) =>
  state === V2RuntimeState.FAILED && message === 'terminated' ? V2RuntimeState.CANCELED : state;
