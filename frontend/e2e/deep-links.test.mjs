// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { authMode, connect, fixture, launch, origin, requireTokens } from './live.mjs';

test(
  'a detail page opened directly, without a namespace query, stays put (C56)',
  { timeout: 600000 },
  async () => {
    requireTokens();
    const { run_id: uid } = await fixture('markdown');
    const { browser, page, errors } = await launch();
    try {
      // A bookmark or pasted link: the proxy's own namespace, no ?namespace=.
      await page.goto(`${origin}/argo.html#/runs/details/${uid}`);
      if ((await authMode()) === 'token') await connect(page);
      await page.locator('#sideNav').waitFor();
      await page.getByRole('button', { name: 'Graph', exact: true }).waitFor();
      assert.ok(page.url().includes(`/runs/details/${uid}`), page.url());
      assert.deepEqual(errors, []);
    } finally {
      await browser.close();
    }
  },
);
