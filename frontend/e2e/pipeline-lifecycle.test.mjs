// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
// The upstream "hello world" integration journey, through the native UI only:
// upload a pipeline file, read its graph, create an experiment from it, start a
// run in that experiment and one without, read run details and logs, find both
// runs and experiments in their lists, filter, and delete the pipeline.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { test } from 'node:test';
import {
  editor,
  fixture,
  go,
  launch,
  namespace,
  open,
  requireTokens,
  shot,
  waitForPhase,
} from './live.mjs';

test(
  'upload, experiment, runs, details, logs, lists and deletion through the UI',
  { timeout: 900000 },
  async () => {
    requireTokens();
    const compiled = await fixture('compile:helloworld');
    const stamp = Date.now();
    const pipelineName = `UI hello world ${stamp}`;
    const experimentName = `UI hello experiment ${stamp}`;
    // A unique parameter value keeps the tasks from hitting an earlier run's cache,
    // so their logs exist.
    const who = `integration-${stamp}`;
    const { browser, page, errors, paths } = await launch({ width: 1500, height: 1000 });
    try {
      await open(page, '/pipelines', editor);
      // 1. Upload the pipeline package through the browser.
      await page.getByRole('button', { name: 'Upload pipeline', exact: true }).click();
      await page.getByLabel('Pipeline Name', { exact: false }).fill(pipelineName);
      await page.locator('input[type=file]').setInputFiles({
        name: 'helloworld.yaml',
        mimeType: 'application/yaml',
        buffer: await readFile(compiled.package),
      });
      await page.getByRole('button', { name: 'Create', exact: true }).click();
      await page.waitForURL(/#\/pipelines\/details\//);
      // 2. The static graph shows the four tasks.
      for (const task of ['greet', 'shout', 'count', 'summarize'])
        await page.getByRole('button', { name: task, exact: true }).waitFor();
      await shot(page, 'lifecycle-pipeline-graph');
      // 3. Create an experiment from the pipeline page.
      await page.getByRole('button', { name: 'Create experiment', exact: true }).click();
      await page.getByLabel('Experiment name', { exact: false }).fill(experimentName);
      await page.getByLabel('Description', { exact: false }).fill('Created from the pipeline page');
      await page.getByRole('button', { name: 'Next', exact: true }).click();
      // 4. The experiment hands off to a new run with the pipeline preselected.
      await page.waitForURL(/#\/runs\/new/);
      const runName = `UI hello run ${stamp}`;
      await page.getByLabel('Run name', { exact: false }).fill(runName);
      await page.getByLabel('Description', { exact: false }).fill('First run from the UI');
      await page.getByLabel('name', { exact: true }).fill(who);
      const firstSubmission = page.waitForResponse(
        (r) =>
          r.request().method() === 'POST' &&
          new URL(r.url()).pathname === `/argo/api/v1/workflows/${namespace}`,
      );
      await page.getByRole('button', { name: 'Start', exact: true }).click();
      const first = await (await firstSubmission).json();
      // 5. Run details: the run appears under its experiment and its detail tab reads back.
      await page.waitForURL(/#\/runs\/details\//);
      await waitForPhase(first.metadata.name, 600000);
      await go(page, `/runs/details/${first.metadata.uid}`);
      await page.getByRole('button', { name: 'Detail', exact: true }).click();
      await page.getByText('Run ID', { exact: true }).waitFor();
      await page.getByText(first.metadata.uid, { exact: true }).waitFor();
      await page.getByText('Created at', { exact: true }).waitFor();
      await page.getByText('First run from the UI', { exact: true }).waitFor();
      await page.getByText(who, { exact: true }).waitFor();
      await page.getByRole('button', { name: 'Graph', exact: true }).click();
      assert.ok(
        (await page.locator('.react-flow__node').count()) >= 4,
        'The run graph must show at least four nodes',
      );
      // 6. Clicking a node opens the side panel; its logs load.
      await page.getByRole('button', { name: 'greet', exact: true }).click();
      await page.getByRole('button', { name: 'Input/Output', exact: true }).waitFor();
      await page.getByRole('button', { name: 'Logs', exact: true }).click();
      await page.getByText(`Hello, ${who}`, { exact: true }).waitFor();
      await shot(page, 'lifecycle-run-logs');
      // 7. A second run without choosing an experiment lands in the default one.
      await go(page, '/runs/new');
      await page.getByRole('button', { name: 'Choose', exact: true }).first().click();
      const dialog = page.getByRole('dialog');
      await dialog.getByLabel('Filter pipelines', { exact: true }).fill(pipelineName);
      await dialog.getByTestId('table-row').filter({ hasText: pipelineName }).click();
      await dialog.getByRole('button', { name: 'Use this pipeline', exact: true }).click();
      const secondName = `UI hello second ${stamp}`;
      await page.getByLabel('Run name', { exact: false }).fill(secondName);
      const secondSubmission = page.waitForResponse(
        (r) =>
          r.request().method() === 'POST' &&
          new URL(r.url()).pathname === `/argo/api/v1/workflows/${namespace}`,
      );
      await page.getByRole('button', { name: 'Start', exact: true }).click();
      const second = await (await secondSubmission).json();
      await page.waitForURL(/#\/runs\/(details\/|$)/);
      // 8. Both runs are listed; both experiments are listed and filterable.
      await go(page, '/runs');
      await page.getByLabel('Filter runs', { exact: true }).fill(`UI hello`);
      await page.getByRole('link', { name: runName, exact: true }).waitFor();
      await page.getByRole('link', { name: secondName, exact: true }).waitFor();
      await go(
        page,
        `/experiments/details/${encodeURIComponent(first.metadata.labels['pipelines.kubeflow.org/experiment'])}`,
      );
      await page.getByRole('link', { name: runName, exact: true }).waitFor();
      // The second run was started without choosing an experiment, so, as in
      // stock, it belongs to the Default experiment.
      const defaultExperiment = second.metadata.labels['pipelines.kubeflow.org/experiment'];
      assert.ok(
        defaultExperiment,
        'A run without a chosen experiment must join the Default experiment',
      );
      await go(page, `/experiments/details/${encodeURIComponent(defaultExperiment)}`);
      await page.getByTestId('page-title').filter({ hasText: 'Default' }).waitFor();
      await page.getByRole('link', { name: secondName, exact: true }).waitFor();
      await go(page, '/experiments');
      await page.getByLabel('Filter experiments', { exact: true }).fill(experimentName);
      // The filter request is debounced: wait for the other rows to go.
      await page.getByRole('link', { name: 'Default', exact: true }).waitFor({ state: 'hidden' });
      await page.getByRole('link', { name: experimentName, exact: true }).waitFor();
      await page.getByLabel('Filter experiments', { exact: true }).fill('Default');
      await page.getByRole('link', { name: 'Default', exact: true }).waitFor();
      // 9. Delete the uploaded pipeline from the list.
      await go(page, '/pipelines');
      await page.getByLabel('Filter pipelines', { exact: true }).fill(pipelineName);
      await page
        .getByTestId('table-row')
        .filter({ hasText: pipelineName })
        .locator('input[type=checkbox]')
        .check();
      const deletion = page.waitForResponse(
        (r) => r.request().method() === 'DELETE' && r.url().includes('/configmaps/'),
      );
      await page.getByRole('button', { name: 'Delete', exact: true }).click();
      await page.getByRole('button', { name: 'Confirm', exact: true }).click();
      assert.ok((await deletion).ok());
      await page
        .getByTestId('table-row')
        .filter({ hasText: pipelineName })
        .waitFor({ state: 'detached' });
      assert.ok(
        !paths.some((path) => /^\/(apis|api|system|k8s)\//.test(path)),
        'KFP backend request',
      );
      assert.deepEqual(errors, []);
      assert.ok(second.metadata.uid);
    } finally {
      await browser.close();
    }
  },
);
