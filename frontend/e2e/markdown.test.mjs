// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  archivedRun,
  fixture,
  launch,
  mobile,
  nodeWithArtifact,
  open,
  reader,
  requireTokens,
  shot,
} from './live.mjs';

test(
  'Markdown artifacts render as in stock: formatting kept, raw HTML inert, images fetched',
  { timeout: 600000 },
  async () => {
    requireTokens();
    const { run_id: uid } = await fixture('markdown');
    const node = nodeWithArtifact(await archivedRun(uid), 'document');
    assert.ok(node, 'The markdown run must record a document artifact');
    const { browser, page, errors, hosts } = await launch();
    try {
      await open(page, `/artifacts/${uid}/${node.id}/document`, reader);
      await page.getByRole('button', { name: 'Visualization', exact: true }).click();
      await page.getByRole('heading', { name: 'Evaluation report' }).waitFor();
      await page.getByRole('table').waitFor();
      assert.equal(await page.locator('.markdown-viewer strong').innerText(), 'Passed');
      assert.equal(
        await page
          .locator('.markdown-viewer ul')
          .evaluate((el) => getComputedStyle(el).listStyleType),
        'disc',
      );
      assert.equal(await page.locator('.markdown-viewer script').count(), 0);
      assert.equal(await page.evaluate(() => window.__unexpectedMarkdownExecution), undefined);
      assert.ok(
        hosts.includes('tracker.invalid'),
        'Remote images are requested as the stock viewer does (C24 parity)',
      );
      await shot(page, 'markdown', { fullPage: true });
      await mobile(page, 'markdown');
      assert.deepEqual(errors, []);
    } finally {
      await browser.close();
    }
  },
);
