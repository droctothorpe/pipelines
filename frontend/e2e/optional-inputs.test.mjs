// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  editor,
  failures,
  fixture,
  launch,
  namespace,
  open,
  requireTokens,
  waitForPhase,
} from './live.mjs';

test(
  'the run form preserves None and literal null in SDK-compatible parameters',
  { timeout: 900000 },
  async () => {
    requireTokens();
    const version = await fixture('optional-version');
    const { browser, page, errors } = await launch();
    try {
      const hash = `/runs/new?pipelineVersionId=${version.version_id}&experimentId=${version.experiment_id}`;
      await open(page, hash, editor);
      for (const value of [null, 'null']) {
        if (value !== null)
          await page.evaluate((h) => {
            window.location.hash = h;
          }, hash);
        await page.getByRole('checkbox', { name: 'Use None for value' }).waitFor();
        assert.equal(
          await page.getByRole('checkbox', { name: 'Use None for value' }).isChecked(),
          true,
        );
        if (value !== null) {
          await page.getByRole('checkbox', { name: 'Use None for value' }).uncheck();
          await page.getByLabel('value', { exact: true }).fill(value);
          await page.getByLabel('expected', { exact: true }).fill(JSON.stringify(value));
        }
        await page.getByLabel('Run name', { exact: false }).fill('UI optional ' + Date.now());
        const submitted = page.waitForResponse(
          (r) =>
            r.request().method() === 'POST' &&
            new URL(r.url()).pathname === `/argo/api/v1/workflows/${namespace}`,
        );
        await page.getByRole('button', { name: 'Start', exact: true }).click();
        const response = await submitted;
        assert.ok(response.ok());
        const run = await response.json();
        assert.equal(
          JSON.parse(run.metadata.annotations['pipelines.kubeflow.org/parameters']).value,
          value,
        );
        const complete = await waitForPhase(run.metadata.name);
        assert.equal(complete.status.phase, 'Succeeded', JSON.stringify(failures(complete)));
      }
      assert.deepEqual(errors, []);
    } finally {
      await browser.close();
    }
  },
);
