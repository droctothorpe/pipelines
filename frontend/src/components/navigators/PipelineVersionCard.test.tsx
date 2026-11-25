// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import type {
  PipelineSummary as V2Pipeline,
  VersionSummary as V2PipelineVersion,
} from 'src/lib/NativeViewTypes';
import { PipelineVersionCard } from './PipelineVersionCard';

const OLD_VERSION_NAME = 'old version';
const NEW_VERSION_NAME = 'new version';
const TEST_PIPELINE_ID = 'pipeline-id';

const OLD_TEST_PIPELINE_VERSION_ID = 'old-version-id';
const OLD_TEST_PIPELINE_VERSION: V2PipelineVersion = {
  code_source_url: 'https://github.com/kubeflow/pipelines',
  created_at: '2021-11-24T20:58:23.000Z',
  description: 'This is old version description.',
  display_name: OLD_VERSION_NAME,
  pipeline_version_id: OLD_TEST_PIPELINE_VERSION_ID,
};

const NEW_TEST_PIPELINE_VERSION_ID = 'new-version-id';
const NEW_TEST_PIPELINE_VERSION: V2PipelineVersion = {
  created_at: '2021-12-24T20:58:23.000Z',
  description: 'This is new version description.',
  display_name: NEW_VERSION_NAME,
  pipeline_version_id: NEW_TEST_PIPELINE_VERSION_ID,
};

const TEST_PIPELINE_VERSIONS_LIST: V2PipelineVersion[] = [
  OLD_TEST_PIPELINE_VERSION,
  NEW_TEST_PIPELINE_VERSION,
];

const TEST_PIPELINE: V2Pipeline = {
  created_at: '2021-11-24T20:58:23.000Z',
  description: 'This is pipeline level description.',
  pipeline_id: TEST_PIPELINE_ID,
};

describe('PipelineVersionCard', () => {
  it('makes Show Summary button visible by default', async () => {
    render(
      <PipelineVersionCard
        pipeline={TEST_PIPELINE}
        selectedVersion={OLD_TEST_PIPELINE_VERSION}
        versions={TEST_PIPELINE_VERSIONS_LIST}
        handleVersionSelected={() => Promise.resolve()}
      ></PipelineVersionCard>,
    );

    screen.getByText('Show Summary');
    expect(screen.queryByText('Hide')).toBeNull();
  });

  it('clicks to open and hide Summary', async () => {
    render(
      <PipelineVersionCard
        pipeline={TEST_PIPELINE}
        selectedVersion={OLD_TEST_PIPELINE_VERSION}
        versions={TEST_PIPELINE_VERSIONS_LIST}
        handleVersionSelected={() => Promise.resolve()}
      ></PipelineVersionCard>,
    );

    await userEvent.click(screen.getByText('Show Summary'));
    expect(screen.queryByText('Show Summary')).toBeNull();
    await userEvent.click(screen.getByText('Hide'));
    screen.getByText('Show Summary');
  });

  it('shows Summary and checks detail', async () => {
    render(
      <PipelineVersionCard
        pipeline={TEST_PIPELINE}
        selectedVersion={OLD_TEST_PIPELINE_VERSION}
        versions={TEST_PIPELINE_VERSIONS_LIST}
        handleVersionSelected={() => Promise.resolve()}
      ></PipelineVersionCard>,
    );

    await userEvent.click(screen.getByText('Show Summary'));

    screen.getByText('Pipeline ID');
    screen.getByText(TEST_PIPELINE_ID);
    screen.getByText('Version');
    screen.getByText(OLD_VERSION_NAME);
    const versionSource = screen.getByText('Version source');
    expect(versionSource).toHaveAttribute('href', 'https://github.com/kubeflow/pipelines');
    screen.getByText('Uploaded on');
    screen.getByText(new Date('2021-11-24T20:58:23.000Z').toLocaleString());
    screen.getByText('Pipeline Description');
    screen.getByText('This is pipeline level description.');
    screen.getByText('Version Description');
    screen.getByText('This is old version description.');
  });

  it('does not render the Version source link for an unsafe code_source_url scheme', async () => {
    render(
      <PipelineVersionCard
        pipeline={TEST_PIPELINE}
        selectedVersion={{
          ...OLD_TEST_PIPELINE_VERSION,
          code_source_url: 'javascript:alert(1)',
        }}
        versions={TEST_PIPELINE_VERSIONS_LIST}
        handleVersionSelected={() => Promise.resolve()}
      ></PipelineVersionCard>,
    );

    await userEvent.click(screen.getByText('Show Summary'));

    // The summary still renders, but the unsafe link is dropped entirely.
    screen.getByText('Uploaded on');
    expect(screen.queryByText('Version source')).toBeNull();
  });

  it('shows version list', async () => {
    const { getByRole } = render(
      <PipelineVersionCard
        pipeline={TEST_PIPELINE}
        selectedVersion={OLD_TEST_PIPELINE_VERSION}
        versions={TEST_PIPELINE_VERSIONS_LIST}
        handleVersionSelected={() => Promise.resolve()}
      ></PipelineVersionCard>,
    );

    await userEvent.click(screen.getByText('Show Summary'));

    fireEvent.mouseDown(getByRole('combobox'));
    await screen.findByRole('listbox');
    screen.getByRole('option', { name: NEW_VERSION_NAME });
  });
});
