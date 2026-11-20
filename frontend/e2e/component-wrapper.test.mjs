// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  archivedRun,
  fixture,
  launch,
  mobile,
  nodeNamed,
  open,
  reader,
  requireTokens,
  shot,
} from './live.mjs';

// The deliberately invalid raw-container run: native validation stays inside
// the user's component while its error and pod logs remain visible.
test(
  'validation errors stay inside the user component with logs from the real pod',
  { timeout: 600000 },
  async () => {
    requireTokens();
    const { run_id: uid } = await fixture('validation');
    const node = nodeNamed(await archivedRun(uid), 'produce');
    assert.equal(node.phase, 'Error');
    const { browser, page, errors, paths } = await launch();
    try {
      await open(page, `/runs/details/${uid}?task=${encodeURIComponent(node.id)}`, reader);
      await page.getByRole('alert').filter({ hasText: 'invalid operation' }).waitFor();
      assert.equal(await page.locator('.react-flow__node-SUB_DAG').count(), 0);
      await shot(page, 'validation-error', { fullPage: true });
      await page.getByRole('button', { name: 'Task Details', exact: true }).click();
      await page.getByText('Container', { exact: true }).waitFor();
      const logResponse = page.waitForResponse((response) => response.url().endsWith('/main-logs'));
      await page.getByRole('button', { name: 'Logs', exact: true }).click();
      assert.equal((await logResponse).status(), 200);
      await page
        .getByTestId('log-status')
        .filter({ hasText: /Archived logs|Live log stream ended/ })
        .waitFor();
      assert.ok(!(await page.locator('body').innerText()).includes('task pod is not available'));
      assert.ok(paths.some((path) => path.includes('/main-logs')));
      assert.ok(
        !paths.some((path) => path.includes(`/${node.id}/main-logs`)),
        'Logs must use the actual execution pod',
      );
      await mobile(page, 'validation-error');
      assert.deepEqual(errors, []);
    } finally {
      await browser.close();
    }
  },
);
