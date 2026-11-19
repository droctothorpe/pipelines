// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { chromium } from 'playwright';

// Read-only check against the deployed UI, with a namespace-scoped token.
test(
  'native deployment retains the stock KFP navigation and list presentation',
  { timeout: 60000 },
  async () => {
    const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome' });
    try {
      const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
      const paths = [],
        errors = [];
      page.on('request', (request) => paths.push(new URL(request.url()).pathname));
      page.on('pageerror', (error) => errors.push(error.message));
      await page.goto(
        `${process.env.ARGO_UI_URL || 'http://127.0.0.1:3003'}/argo.html?namespace=${process.env.ARGO_NAMESPACE || 'kfp-argo'}`,
      );
      await page.getByLabel('Kubernetes bearer token').fill(process.env.ARGO_READER_TOKEN || '');
      await page.getByRole('button', { name: 'Connect', exact: true }).click();
      await page.getByRole('dialog').waitFor({ state: 'hidden' });
      await page.screenshot({
        path: process.env.KFP_UI_SCREENSHOT || '/tmp/kfp-ui-restoration.png',
        fullPage: true,
      });
      assert.equal(
        await page.locator('#sideNav').count(),
        1,
        'Expected the original KFP left navigation, not prototype tabs',
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
      await page.getByRole('button', { name: 'Create run', exact: true }).waitFor();
      await page.getByRole('button', { name: 'Active', exact: true }).waitFor();
      await page.getByRole('button', { name: 'Archived', exact: true }).waitFor();
      await page.screenshot({
        path: process.env.KFP_UI_SCREENSHOT || '/tmp/kfp-ui-restoration.png',
        fullPage: true,
      });
      assert.ok(
        !paths.some((path) => /^\/(apis|api|system|k8s)\//.test(path)),
        'KFP backend request',
      );
      assert.deepEqual(errors, []);
    } finally {
      await browser.close();
    }
  },
);
