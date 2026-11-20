// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  archivedRun,
  editor,
  encode,
  fixture,
  go,
  launch,
  mobile,
  nodeWithArtifact,
  open,
  requireTokens,
  shot,
} from './live.mjs';

test(
  'dataset and model viewers show native previews without loading payloads',
  { timeout: 1200000 },
  async () => {
    requireTokens();
    const { run_id: uid } = await fixture('preview');
    const node = nodeWithArtifact(await archivedRun(uid), 'dataset-preview');
    assert.ok(node, 'The preview run must upload a dataset preview');
    const { browser, page, errors, paths } = await launch({ width: 1280, height: 720 });
    try {
      await open(page, `/artifacts/${uid}/${encode(node.id)}/dataset`, editor);
      await page.getByRole('button', { name: 'Visualization', exact: true }).click();
      await page.getByRole('table', { name: 'Dataset sample' }).waitFor();
      await page.getByRole('columnheader', { name: /feature_00/ }).waitFor();
      await shot(page, 'preview-dataset');
      await mobile(page, 'preview-dataset');
      await go(page, `/artifacts/${uid}/${encode(node.id)}/model`);
      await page.getByRole('button', { name: 'Visualization', exact: true }).click();
      await page.getByRole('region', { name: 'Model preview' }).waitFor();
      await page.getByText('xgboost', { exact: true }).waitFor();
      await page.getByRole('table', { name: 'Recorded hyperparameters' }).waitFor();
      await shot(page, 'preview-model');
      await mobile(page, 'preview-model');
      assert.ok(paths.some((path) => path.endsWith('/dataset-preview')));
      assert.ok(paths.some((path) => path.endsWith('/model-preview')));
      assert.ok(
        !paths.some((path) => path.includes('/argo/artifacts/') && /\/(dataset|model)$/.test(path)),
        'Previews must not download artifact payloads',
      );
      assert.deepEqual(errors, []);
    } finally {
      await browser.close();
    }
  },
);

test(
  'ROC and confusion-matrix viewers consume native classification metadata',
  { timeout: 600000 },
  async () => {
    requireTokens();
    const { run_id: uid } = await fixture('classification');
    const node = nodeWithArtifact(await archivedRun(uid), 'metrics');
    assert.ok(node);
    const { browser, page, errors } = await launch();
    try {
      await open(page, `/artifacts/${uid}/${encode(node.id)}/metrics`, editor);
      await page.getByRole('button', { name: 'Visualization', exact: true }).click();
      await page.getByText('ROC Curve', { exact: true }).waitFor();
      await page.getByText('Confusion Matrix: metrics', { exact: true }).waitFor();
      await page.waitForFunction(() => {
        const curve = document.querySelector('.recharts-line-curve');
        if (!curve || !(curve.getAttribute('d')?.length > 10)) return false;
        const dash = getComputedStyle(curve).strokeDasharray;
        return dash === 'none' || parseFloat(dash) >= curve.getTotalLength() - 1;
      });
      await shot(page, 'classification', { fullPage: true });
      assert.deepEqual(errors, []);
    } finally {
      await browser.close();
    }
  },
);
