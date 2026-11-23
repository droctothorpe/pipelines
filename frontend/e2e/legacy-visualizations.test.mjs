// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  archivedRun,
  editor,
  encode,
  fixture,
  launch,
  mobile,
  nodeWithArtifact,
  open,
  requireTokens,
  shot,
} from './live.mjs';

test(
  'legacy mlpipeline-ui-metadata outputs route to the kept viewers',
  { timeout: 600000 },
  async () => {
    requireTokens();
    const { run_id: uid } = await fixture('ui-metadata');
    const run = await archivedRun(uid);
    const node = nodeWithArtifact(run, 'mlpipeline_ui_metadata');
    assert.ok(node, 'The task must upload its mlpipeline_ui_metadata artifact');
    const { browser, page, errors, paths } = await launch({ width: 1280, height: 720 });
    try {
      await open(page, `/artifacts/${uid}/${encode(node.id)}/mlpipeline_ui_metadata`, editor);
      await page.getByRole('button', { name: 'Visualization', exact: true }).click();
      const table = page.getByRole('table', { name: 'Legacy table' });
      await table.waitFor();
      await table.getByRole('columnheader', { name: 'accuracy' }).waitFor();
      await table.getByRole('cell', { name: 'tuned' }).waitFor();
      await page.getByRole('region', { name: 'confusion_matrix visualization' }).waitFor();
      await page.getByText('negative', { exact: true }).first().waitFor();
      await page.getByRole('region', { name: 'roc visualization' }).waitFor();
      await page.waitForFunction(() => {
        const curve = document.querySelector('.recharts-line-curve');
        return !!curve && (curve.getAttribute('d')?.length ?? 0) > 10;
      });
      await page.getByRole('heading', { name: 'Legacy summary' }).waitFor();
      const frame = page.frameLocator('iframe[title="Legacy web app 5"]');
      await frame.getByRole('heading', { name: 'Legacy web app' }).waitFor();
      assert.notEqual(await page.title(), 'x', 'Sandboxed web apps must not run scripts');
      await page.getByText(/TensorBoard viewers are not launched/).waitFor();
      await shot(page, 'legacy-ui-metadata', { fullPage: true });
      await mobile(page, 'legacy-ui-metadata');
      assert.ok(
        paths.some((path) => path.endsWith('/mlpipeline_ui_metadata')),
        'The metadata file is read through Argo Server',
      );
      assert.ok(
        paths.some((path) => path.endsWith('/table')),
        "A table source naming this task's artifact URI is read through Argo Server",
      );
      assert.deepEqual(errors, []);
    } finally {
      await browser.close();
    }
  },
);
