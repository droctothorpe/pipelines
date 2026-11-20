// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { launch, open, reader, requireTokens, shot } from './live.mjs';

// Read-only: the deployed UI keeps the stock navigation and list presentation
// and never calls a retired KFP backend path.
test('the deployment keeps the stock navigation and lists', { timeout: 120000 }, async () => {
  requireTokens();
  const { browser, page, errors, paths } = await launch();
  try {
    await open(page, '/pipelines', reader);
    assert.equal(
      await page.locator('#sideNav').count(),
      1,
      'Expected the original KFP left navigation',
    );
    for (const id of [
      'pipelinesBtn',
      'experimentsBtn',
      'runsBtn',
      'recurringRunsBtn',
      'artifactsBtn',
    ])
      assert.equal(await page.locator('#' + id).count(), 1, id);
    await page.locator('#runsBtn').click();
    await page.getByTestId('page-title').filter({ hasText: 'Runs' }).waitFor();
    await page.getByText('Run name', { exact: true }).waitFor();
    for (const name of ['Create run', 'Active', 'Archived'])
      await page.getByRole('button', { name, exact: true }).waitFor();
    await shot(page, 'stock-navigation', { fullPage: true });
    assert.ok(
      !paths.some((path) => /^\/(apis|api|system|k8s)\//.test(path)),
      'KFP backend request',
    );
    assert.deepEqual(errors, []);
  } finally {
    await browser.close();
  }
});
