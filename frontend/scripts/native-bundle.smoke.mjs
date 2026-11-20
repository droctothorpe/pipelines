// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import assert from 'node:assert/strict';
import { mkdir, readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { test } from 'node:test';
import { chromium } from 'playwright';

const views = [
  [
    'pipelines',
    'Pipelines',
    ['Pipeline name', 'Description', 'Uploaded on'],
    'No pipelines found. Click "Upload pipeline" to start.',
  ],
  [
    'runs',
    'Runs',
    [
      'Run name',
      'Status',
      'Duration',
      'Experiment',
      'Pipeline Version',
      'Recurring Run',
      'Start time',
    ],
    'No available runs found.',
  ],
  [
    'experiments',
    'Experiments',
    ['Experiment name', 'Description', 'Last 5 runs'],
    'No experiments found. Click "Create experiment" to start.',
  ],
  [
    'recurringRuns',
    'Recurring Runs',
    [
      'Recurring Run Name',
      'Status',
      'Trigger',
      'Start Time',
      'End Time',
      'Schedule Status',
      'Experiment',
      'Created at',
    ],
    'No available recurring runs found.',
  ],
  [
    'artifacts',
    'Artifacts',
    ['Name', 'ID', 'Type', 'URI', 'Namespace', 'Created at'],
    'No artifacts found.',
  ],
];
const token = 'namespace-test-token';
async function mount(browser, entry, inventory = {}, authMode = 'token') {
  const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });
  const errors = [],
    requests = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.route('**/*', async (route) => {
    const request = route.request(),
      url = new URL(request.url());
    assert.equal(url.origin, 'http://localhost');
    if (url.pathname.endsWith('.html') || url.pathname.startsWith('/static/')) {
      const file = url.pathname.slice(1);
      const type = file.endsWith('.js')
        ? 'text/javascript'
        : file.endsWith('.css')
          ? 'text/css'
          : file.endsWith('.png')
            ? 'image/png'
            : 'text/html';
      return route.fulfill({
        body: await readFile(new URL(`../build/${file}`, import.meta.url)),
        contentType: type,
      });
    }
    if (url.pathname === '/config.json') {
      // Token-mode deployments may predate the config endpoint; single-user
      // proxies publish their mode so the UI skips the login dialog.
      return authMode === 'single-user'
        ? route.fulfill({
            contentType: 'application/json',
            body: JSON.stringify({ authMode, namespace: 'team' }),
          })
        : route.fulfill({ status: 404 });
    }
    requests.push(url.pathname);
    assert.ok(
      /^\/(argo|kubernetes)\//.test(url.pathname),
      `Retired backend request: ${url.pathname}`,
    );
    assert.equal(
      request.headers().authorization,
      authMode === 'single-user' ? undefined : `Bearer ${token}`,
    );
    const handled = await inventory.handleRequest?.(request, url);
    if (handled) return route.fulfill(handled);
    let body = { items: [] };
    if (url.pathname === '/kubernetes/apis/argoproj.io/v1alpha1/namespaces/team/workflows') {
      assert.ok(request.headers().accept.includes('as=PartialObjectMetadataList'));
      body = {
        items: (inventory.runs || []).map((run) => ({
          metadata: { resourceVersion: '1', ...run.metadata },
        })),
      };
    } else if (url.pathname === '/argo/api/v1/workflows/team') {
      assert.equal(
        url.searchParams.get('listOptions.fieldSelector'),
        'ext.showRemainingItemCount=true',
      );
      assert.ok(url.searchParams.get('fields').includes('items.status.phase'));
      assert.ok(!url.searchParams.get('fields').includes('items.status.nodes'));
      body = {
        items: (inventory.runs || []).map((run) => ({
          metadata: { resourceVersion: '1', ...run.metadata },
          spec: {
            shutdown: run.spec?.shutdown,
            workflowTemplateRef: run.spec?.workflowTemplateRef,
          },
          status: {
            phase: run.status?.phase,
            startedAt: run.status?.startedAt,
            finishedAt: run.status?.finishedAt,
            message: run.status?.message,
          },
        })),
      };
    } else if (url.pathname.endsWith('/workflow-templates/team'))
      body = { items: inventory.versions || [] };
    else if (url.pathname.includes('/workflows/team/'))
      body =
        inventory.runs?.find(
          (run) => run.metadata.name === decodeURIComponent(url.pathname.split('/').pop()),
        ) || {};
    else if (url.pathname.endsWith('/kfp-metadata')) body = inventory.metadata || {};
    else if (url.pathname.endsWith('/main-logs'))
      return route.fulfill({ contentType: 'text/plain', body: 'training complete\n' });
    else if (url.pathname.endsWith('/dataset'))
      return route.fulfill({ contentType: 'text/plain', body: 'x,y\n1,2\n' });
    return route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) });
  });
  // Single-user proxies publish their namespace, so the URL needs none.
  await page.goto(`http://localhost/${entry}${authMode === 'token' ? '?namespace=team' : ''}`);
  if (authMode === 'token') {
    await page.getByLabel('Kubernetes bearer token').fill(token);
    await page.getByRole('button', { name: 'Connect', exact: true }).click();
    await page.getByRole('dialog').waitFor({ state: 'hidden' });
  }
  return { page, errors, requests };
}

test('single-user proxies skip the token dialog, default the namespace and send no browser credentials', async () => {
  const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || undefined });
  try {
    const { page, errors, requests } = await mount(browser, 'argo.html', {}, 'single-user');
    await page.getByText('No pipelines found.', { exact: false }).waitFor();
    assert.equal(await page.getByRole('dialog').count(), 0);
    assert.equal(await page.getByLabel('Kubernetes bearer token').count(), 0);
    assert.ok(requests.some((path) => path.startsWith('/kubernetes/')));
    await page.reload();
    await page.getByText('No pipelines found.', { exact: false }).waitFor();
    assert.equal(await page.getByRole('dialog').count(), 0);
    assert.deepEqual(errors, []);
    await page.close();
  } finally {
    await browser.close();
  }
});

test(
  'production entrypoints retain stock navigation, list columns and forms at desktop and mobile sizes',
  { timeout: 90000 },
  async () => {
    const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || undefined });
    try {
      for (const entry of ['index.html', 'argo.html']) {
        const { page, errors, requests } = await mount(browser, entry);
        for (const [id, title, columns, empty] of views) {
          await page.locator(`#${id}Btn`).click();
          await page.getByText(empty, { exact: true }).waitFor();
          assert.equal(await page.getByTestId('page-title').innerText(), title);
          for (const column of columns) await page.getByText(column, { exact: true }).waitFor();
          assert.equal(
            await page.locator('#sideNav').evaluate((el) => el.getBoundingClientRect().width),
            220,
          );
          assert.ok(!(await page.locator('body').innerText()).includes('Argo prototype'));
        }
        await page.locator('#pipelinesBtn').click();
        await page.getByRole('button', { name: 'Upload pipeline', exact: true }).click();
        await page.getByLabel('Pipeline Name', { exact: false }).waitFor();
        assert.equal(await page.getByTestId('page-title').innerText(), 'New Pipeline');
        await page.getByRole('button', { name: 'Cancel', exact: true }).click();
        await page.locator('#experimentsBtn').click();
        await page.getByRole('button', { name: 'Create experiment', exact: true }).click();
        await page.getByLabel('Experiment name', { exact: false }).waitFor();
        assert.equal(await page.getByTestId('page-title').innerText(), 'New experiment');
        await page.getByRole('button', { name: 'Cancel', exact: true }).click();
        await page.locator('#runsBtn').click();
        await page.getByRole('button', { name: 'Create run', exact: true }).click();
        await page.getByLabel('Run name', { exact: false }).waitFor();
        assert.equal(await page.getByTestId('page-title').innerText(), 'Start a new run');
        await page.setViewportSize({ width: 390, height: 844 });
        await page.waitForFunction(
          () => document.querySelector('#sideNav').getBoundingClientRect().width === 72,
        );
        await page.locator('#runsBtn').click();
        await page.getByText('No available runs found.', { exact: true }).waitFor();
        assert.ok(
          requests.some((path) => path.startsWith('/kubernetes/api/v1/namespaces/team/configmaps')),
        );
        const stored = await page.evaluate(() => JSON.stringify([localStorage, sessionStorage]));
        assert.ok(!stored.includes(token), 'A bearer token was persisted');
        assert.ok(!page.url().includes(token));
        await page.reload();
        await page.getByLabel('Kubernetes bearer token').waitFor();
        assert.equal(await page.getByLabel('Kubernetes bearer token').inputValue(), '');
        assert.deepEqual(errors, []);
        await page.close();
      }
    } finally {
      await browser.close();
    }
  },
);

test(
  'production run graph has stock tabs, typed artifacts, downloads, task logs and timeline',
  { timeout: 60000 },
  async () => {
    const run = {
      metadata: {
        name: 'run-one',
        namespace: 'team',
        uid: 'uid-one',
        creationTimestamp: '2026-01-01T00:00:00Z',
      },
      spec: { arguments: { parameters: [{ name: 'factor', value: '1' }] } },
      status: {
        phase: 'Succeeded',
        startedAt: '2026-01-01T00:00:00Z',
        finishedAt: '2026-01-01T00:01:00Z',
        nodes: {
          root: { id: 'run-one', displayName: 'run-one', type: 'DAG', children: ['prepare'] },
          prepare: {
            id: 'prepare',
            displayName: 'prepare',
            type: 'Pod',
            boundaryID: 'run-one',
            phase: 'Succeeded',
            startedAt: '2026-01-01T00:00:00Z',
            finishedAt: '2026-01-01T00:01:00Z',
            outputs: {
              artifacts: [{ name: 'dataset' }, { name: 'kfp-metadata' }, { name: 'main-logs' }],
            },
          },
        },
      },
    };
    const producer = { run: 'uid-one', task: 'prepare', namespace: 'team' };
    const metadata = {
      schema: 'kfp-argo/v1',
      producer,
      inputs: [],
      metrics: { score: 0.75 },
      artifacts: [
        {
          port: 'dataset',
          type: 'system.Dataset@0.0.1',
          uri: 's3://data/dataset',
          producer,
          metadata: { nested: { rows: 4 } },
        },
      ],
    };
    const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || undefined });
    try {
      const { page, errors, requests } = await mount(browser, 'argo.html', {
        runs: [run],
        metadata,
      });
      await page.locator('#runsBtn').click();
      await page.getByRole('link', { name: 'run-one', exact: true }).click();
      for (const tab of ['Graph', 'Timeline', 'Detail', 'Pipeline Spec'])
        await page.getByRole('button', { name: tab, exact: true }).waitFor();
      await page.getByRole('button', { name: 'prepare', exact: true }).click();
      assert.equal(await page.getByRole('button', { name: 'System Logs', exact: true }).count(), 0);
      await page.getByRole('link', { name: 'system.Dataset@0.0.1', exact: true }).waitFor();
      assert.ok(!(await page.locator('body').innerText()).includes('[object Object]'));
      const downloading = page.waitForEvent('download');
      await page.getByRole('button', { name: 'Download', exact: true }).click();
      assert.equal(await readFile(await (await downloading).path(), 'utf8'), 'x,y\n1,2\n');
      await page.getByRole('button', { name: 'Logs', exact: true }).click();
      await page.getByText('training complete', { exact: true }).waitFor();
      await page.getByRole('button', { name: 'dataset', exact: true }).click();
      await page.getByRole('button', { name: 'Visualization', exact: true }).waitFor();
      await page.getByText('nested', { exact: true }).waitFor();
      await page.getByRole('button', { name: 'Timeline', exact: true }).click();
      await page.getByText('prepare', { exact: true }).first().waitFor();
      await page.getByRole('button', { name: 'Detail', exact: true }).click();
      await page.getByText('uid-one', { exact: true }).waitFor();
      assert.ok(!requests.some((path) => path.endsWith('worker-json.js')));
      assert.deepEqual(errors, []);
      await page.close();
    } finally {
      await browser.close();
    }
  },
);

test(
  'production experiment archival refreshes children without stopping runs',
  { timeout: 60000 },
  async () => {
    const resource = 'pipelines.kubeflow.org/resource';
    const experimentLabel = 'pipelines.kubeflow.org/experiment';
    const maps = new Map([
      [
        'experiment-map',
        {
          apiVersion: 'v1',
          kind: 'ConfigMap',
          metadata: {
            name: 'experiment-map',
            uid: 'experiment-id',
            namespace: 'team',
            resourceVersion: '1',
            labels: { [resource]: 'experiment' },
          },
          data: {
            displayName: 'Archive verification',
            description: 'Owned test fixture; no real cluster requests.',
            storageState: 'AVAILABLE',
          },
        },
      ],
    ]);
    let schedule = {
      apiVersion: 'argoproj.io/v1alpha1',
      kind: 'CronWorkflow',
      metadata: {
        name: 'training-daily',
        uid: 'schedule-id',
        namespace: 'team',
        resourceVersion: '1',
      },
      spec: {
        suspend: false,
        workflowMetadata: { labels: { [experimentLabel]: 'experiment-id' } },
      },
    };
    const run = {
      metadata: {
        name: 'training-run',
        uid: 'run-id',
        namespace: 'team',
        creationTimestamp: '2026-11-20T11:59:00Z',
        labels: { [experimentLabel]: 'experiment-id' },
      },
      spec: {},
      status: { phase: 'Running' },
    };
    const writes = [];
    const json = (body, status = 200) => ({
      status,
      contentType: 'application/json',
      body: JSON.stringify(body),
    });
    const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || undefined });
    try {
      const { page, errors } = await mount(browser, 'argo.html', {
        runs: [run],
        handleRequest: async (request, url) => {
          const method = request.method(),
            path = url.pathname;
          if (method !== 'GET') writes.push({ method, path });
          if (path === '/argo/api/v1/cron-workflows/team') return json({ items: [schedule] });
          if (path === '/argo/api/v1/cron-workflows/team/training-daily' && method === 'PUT') {
            const body = request.postDataJSON().cronWorkflow;
            assert.equal(body.metadata.uid, schedule.metadata.uid);
            assert.equal(body.metadata.resourceVersion, schedule.metadata.resourceVersion);
            schedule = {
              ...body,
              metadata: {
                ...body.metadata,
                resourceVersion: String(Number(body.metadata.resourceVersion) + 1),
              },
            };
            return json(schedule);
          }
          const root = '/kubernetes/api/v1/namespaces/team/configmaps';
          if (path === root) {
            if (method === 'POST') {
              const body = request.postDataJSON();
              body.metadata.uid = 'state-id';
              body.metadata.resourceVersion = '1';
              maps.set(body.metadata.name, body);
              return json(body, 201);
            }
            const selector = url.searchParams.get('labelSelector') || '';
            const [key, value] = selector.split('=');
            return json({
              items: [...maps.values()].filter(
                (item) => !selector || item.metadata.labels?.[key] === value,
              ),
            });
          }
          if (path.startsWith(root + '/')) {
            const name = decodeURIComponent(path.slice(root.length + 1));
            const stored = maps.get(name);
            if (!stored) return json({}, 404);
            if (method === 'PUT') {
              const body = request.postDataJSON();
              assert.equal(body.metadata.uid, stored.metadata.uid);
              assert.equal(body.metadata.resourceVersion, stored.metadata.resourceVersion);
              body.metadata.resourceVersion = String(Number(body.metadata.resourceVersion) + 1);
              maps.set(name, body);
              return json(body);
            }
            return json(stored);
          }
          return undefined;
        },
      });
      await page.clock.setFixedTime(new Date('2026-11-20T12:00:00Z'));
      await page.setViewportSize({ width: 1280, height: 900 });
      await page.locator('#experimentsBtn').click();
      await page.getByRole('link', { name: 'Archive verification', exact: true }).click();
      await page.getByText('1 active', { exact: true }).waitFor();
      await page.getByRole('link', { name: 'training-run', exact: true }).waitFor();
      const evidence = process.env.KFP_UI_EVIDENCE_DIR;
      if (evidence) {
        await mkdir(evidence, { recursive: true });
        await page.screenshot({
          path: join(evidence, 'experiment-before-archive.png'),
          animations: 'disabled',
        });
      }
      await page.locator('#archiveBtn').click();
      await page
        .getByText('Archive this experiment and its runs, and disable recurring runs.', {
          exact: false,
        })
        .waitFor();
      if (evidence)
        await page.screenshot({
          path: join(evidence, 'experiment-archive-confirmation.png'),
          animations: 'disabled',
        });
      await page.getByRole('button', { name: 'Confirm', exact: true }).click();
      await page.getByRole('button', { name: 'Restore', exact: true }).waitFor();
      await page.getByText('0 active', { exact: true }).waitFor();
      await page.getByRole('link', { name: 'training-run', exact: true }).waitFor();
      assert.equal(maps.get('experiment-map').data.storageState, 'ARCHIVED');
      assert.equal(maps.get('run-run-id').data.storageState, 'ARCHIVED');
      assert.equal(schedule.spec.suspend, true);
      assert.equal(run.status.phase, 'Running');
      assert.equal(run.spec.shutdown, undefined);
      if (evidence)
        await page.screenshot({
          path: join(evidence, 'experiment-after-archive.png'),
          animations: 'disabled',
        });
      await page.locator('#experimentsBtn').click();
      await page.getByRole('button', { name: 'Archived', exact: true }).click();
      await page.getByRole('link', { name: 'Archive verification', exact: true }).waitFor();
      assert.equal(
        await page.getByRole('button', { name: 'Create experiment', exact: true }).count(),
        0,
      );
      assert.equal(await page.getByText('Last 5 runs', { exact: true }).count(), 0);
      await page.getByRole('button', { name: 'Expand', exact: true }).click();
      await page.getByRole('link', { name: 'training-run', exact: true }).waitFor();
      assert.equal(await page.locator('input[type="checkbox"]').count(), 0);
      assert.equal(await page.locator('[data-row-id="run-id"]').getAttribute('tabindex'), '-1');
      assert.equal(await page.getByLabel('Filter runs', { exact: true }).count(), 0);
      if (evidence)
        await page.screenshot({
          path: join(evidence, 'archived-experiments-expanded.png'),
          animations: 'disabled',
        });
      await page.getByRole('link', { name: 'Archive verification', exact: true }).click();
      await page.locator('#archiveBtn').click();
      await page
        .getByText('Its runs stay archived and recurring runs stay disabled.', { exact: false })
        .waitFor();
      await page.getByRole('button', { name: 'Confirm', exact: true }).click();
      await page.getByRole('button', { name: 'Archive', exact: true }).waitFor();
      await page.getByText('No available runs found.', { exact: true }).waitFor();
      assert.equal(maps.get('run-run-id').data.storageState, 'ARCHIVED');
      assert.equal(schedule.spec.suspend, true);
      await page.getByRole('button', { name: 'Archived', exact: true }).click();
      await page.locator('#refreshBtn').click();
      await page.getByRole('link', { name: 'training-run', exact: true }).waitFor();
      assert.ok(
        !writes.some(({ method, path }) => method === 'DELETE' || path.endsWith('/terminate')),
      );
      assert.deepEqual(errors, []);
      await page.close();
    } finally {
      await browser.close();
    }
  },
);
