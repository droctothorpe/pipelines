// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
// Multi-user mode under the Kubeflow central dashboard: the gateway names the
// user, the dashboard names the namespace, and the app lives at /pipeline/.
// Needs a multi-user deployment with ARGO_NAMESPACE set to a tenant namespace
// and KFP_TEST_USER set to an editor there; skips otherwise.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { authMode, encode, fixture, launch, namespace, origin, shot } from './live.mjs';

const header = process.env.KFP_TEST_USERID_HEADER || 'kubeflow-userid';
const editor = process.env.KFP_TEST_USER || '';
const viewer = process.env.KFP_TEST_VIEWER_USER || 'bob@example.com';

/** A stand-in for the central dashboard: embeds the app and speaks its protocol. */
const dashboard = (tenant) => `<!doctype html><title>Kubeflow</title>
<body style="margin:0">
<iframe id="app" src="/pipeline/#/runs" style="width:1400px;height:900px;border:0"></iframe>
<script>
  window.addEventListener('message', (event) => {
    if (event.data?.type !== 'iframe-connected') return;
    const app = document.getElementById('app').contentWindow;
    app.postMessage({ type: 'parent-connected', value: null }, event.origin);
    app.postMessage({ type: 'namespace-selected', value: ${JSON.stringify(tenant)} }, event.origin);
    window.connected = true;
  });
  window.select = (value) =>
    document.getElementById('app').contentWindow.postMessage({ type: 'namespace-selected', value }, location.origin);
</script>`;

test(
  'the dashboard embeds pipelines at /pipeline/ and selects the namespace',
  { timeout: 900000 },
  async (t) => {
    if ((await authMode()) !== 'multi-user' || !editor)
      return t.skip('needs a multi-user deployment');
    const f = await fixture('interop');
    const { browser, page, errors, paths } = await launch(
      { width: 1440, height: 960 },
      { [header]: editor },
    );
    try {
      await page.route(`${origin}/dashboard.html`, (route) =>
        route.fulfill({ contentType: 'text/html', body: dashboard(namespace) }),
      );
      await page.goto(`${origin}/dashboard.html`);
      await page.waitForFunction(() => window.connected === true);
      const app = page.frameLocator('#app');
      await app.getByRole('link', { name: f.run_name, exact: true }).waitFor();
      // The dashboard provides the navigation.
      assert.equal(await app.locator('#sideNav').count(), 0);
      assert.equal(await app.getByRole('dialog').count(), 0);
      await shot(page, 'multi-user-dashboard');
      // Every call went through the dashboard prefix, none to the gateway root.
      const api = paths.filter((path) => /\/(argo|kubernetes)\//.test(path));
      assert.ok(api.length > 0);
      assert.ok(
        api.every((path) => path.startsWith('/pipeline/')),
        api.join('\n'),
      );
      assert.ok(paths.includes('/pipeline/config.json'));
      assert.ok(paths.some((path) => path.startsWith('/pipeline/static/')));
      // A detail page belongs to the namespace that was selected; a switch falls
      // back to its list.
      await app.getByRole('link', { name: f.run_name, exact: true }).click();
      await page.waitForFunction(() =>
        /#\/runs\/details\//.test(document.getElementById('app').contentWindow.location.hash),
      );
      await page.evaluate(() => window.select('kfp-elsewhere'));
      await page.waitForFunction(
        () => document.getElementById('app').contentWindow.location.hash === '#/runs',
      );
      await page.evaluate((tenant) => window.select(tenant), namespace);
      await app.getByRole('link', { name: f.run_name, exact: true }).waitFor();
      assert.deepEqual(errors, []);
    } finally {
      await browser.close();
    }
  },
);

test(
  'outside the dashboard the app keeps its navigation and asks for a namespace',
  { timeout: 300000 },
  async (t) => {
    if ((await authMode()) !== 'multi-user' || !editor)
      return t.skip('needs a multi-user deployment');
    const f = await fixture('interop');
    const { browser, page, errors } = await launch(
      { width: 1440, height: 960 },
      { [header]: editor },
    );
    try {
      await page.goto(`${origin}/pipeline/#/runs`);
      await page.getByLabel('Namespace').fill(namespace);
      await page.getByRole('button', { name: 'Connect', exact: true }).click();
      await page.getByRole('link', { name: f.run_name, exact: true }).waitFor();
      await page.locator('#sideNav').waitFor();
      assert.equal(await page.getByLabel('Kubernetes bearer token').count(), 0);
      await page.goto(`${origin}/pipeline/?namespace=${encode(namespace)}#/experiments`);
      await page.getByRole('link', { name: f.experiment_name, exact: true }).waitFor();
      assert.deepEqual(errors, []);
    } finally {
      await browser.close();
    }
  },
);

test('a viewer sees the tenant but every mutation is refused', { timeout: 300000 }, async (t) => {
  if ((await authMode()) !== 'multi-user' || !editor)
    return t.skip('needs a multi-user deployment');
  const f = await fixture('interop');
  const { browser, page } = await launch({ width: 1440, height: 960 }, { [header]: viewer });
  try {
    await page.goto(`${origin}/pipeline/?namespace=${encode(namespace)}#/runs`);
    await page.getByRole('link', { name: f.run_name, exact: true }).waitFor();
    await page.locator('#experimentsBtn').click();
    await page.getByRole('button', { name: 'Create experiment', exact: true }).click();
    await page.getByLabel('Experiment name', { exact: false }).fill(`Viewer ${f.run_id}`);
    const refused = page.waitForResponse(
      (r) =>
        r.request().method() === 'POST' && r.url().includes('/configmaps') && r.status() === 403,
    );
    await page.getByRole('button', { name: 'Next', exact: true }).click();
    await refused;
    await page.getByRole('dialog').filter({ hasText: '403' }).waitFor();
    await shot(page, 'multi-user-viewer-denied');
  } finally {
    await browser.close();
  }
});
