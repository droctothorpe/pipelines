// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  archivedRun,
  fixture,
  launch,
  nodeNamed,
  open,
  reader,
  requireTokens,
  shot,
} from './live.mjs';

test(
  'nested task deep links expand ancestors and explain pod-free importers',
  { timeout: 600000 },
  async () => {
    requireTokens();
    const { run_id: uid } = await fixture('nested-importer');
    const run = await archivedRun(uid);
    const node = nodeNamed(run, 'importer');
    assert.ok(
      node && node.boundaryID !== run.metadata.name,
      'The importer must sit inside the nested pipeline',
    );
    const { browser, page, errors, paths } = await launch();
    try {
      await open(page, `/runs/details/${uid}?task=${encodeURIComponent(node.id)}`, reader);
      await page.getByRole('button', { name: 'Task Details', exact: true }).click();
      await page.getByText('Importer', { exact: true }).waitFor();
      const ids = await page
        .locator('.react-flow__node')
        .evaluateAll((nodes) => nodes.map((n) => n.getAttribute('data-id') || ''));
      assert.ok(
        ids.some((id) => id.includes(node.id)),
        'The deep-linked importer must be rendered after expanding its ancestors',
      );
      await page.getByRole('button', { name: 'Logs', exact: true }).click();
      await page
        .getByText('This importer resolves an artifact reference without an execution pod.', {
          exact: true,
        })
        .waitFor();
      assert.ok(!paths.some((path) => path.endsWith('/main-logs') || path.endsWith('/log')));
      await shot(page, 'nested-importer', { fullPage: true });
      assert.deepEqual(errors, []);
    } finally {
      await browser.close();
    }
  },
);
