// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
/** Presentation contracts for the retained KFP widgets, not REST API clients. */
export interface ListRequest {
  filter?: string;
  orderAscending?: boolean;
  pageSize?: number;
  pageToken?: string;
  sortBy?: string;
}
export interface BuildInfo {
  apiServerCommitHash?: string;
  apiServerTagName?: string;
  frontendCommitHash?: string;
  frontendTagName?: string;
  buildDate?: string;
  apiServerMultiUser?: boolean;
}
export enum V2PredicateOperation {
  IS_SUBSTRING = 'IS_SUBSTRING',
}
export interface V2Filter {
  predicates: Array<{ key: string; operation: V2PredicateOperation; string_value: string }>;
}
export enum V2RuntimeState {
  RUNTIME_STATE_UNSPECIFIED = 'RUNTIME_STATE_UNSPECIFIED',
  PENDING = 'PENDING',
  RUNNING = 'RUNNING',
  SUCCEEDED = 'SUCCEEDED',
  FAILED = 'FAILED',
  CANCELED = 'CANCELED',
  CANCELING = 'CANCELING',
  PAUSED = 'PAUSED',
  SKIPPED = 'SKIPPED',
}
export interface RunTimingView {
  state?: V2RuntimeState;
  created_at?: Date;
  finished_at?: Date;
}
export interface TaskTimingView {
  task_id?: string;
  name?: string;
  display_name?: string;
  type?: string;
  state?: string;
  create_time?: Date;
  end_time?: Date;
  type_attributes?: { iteration_index?: string };
  pods?: Array<{ type?: string; name?: string; uid?: string }>;
  state_history?: Array<{ state?: string; update_time?: Date; error?: { message?: string } }>;
}
export interface PipelineSummary {
  pipeline_id: string;
  created_at?: string;
  description?: string;
}
export interface VersionSummary {
  pipeline_version_id: string;
  display_name: string;
  created_at?: string;
  description?: string;
  code_source_url?: string;
}
