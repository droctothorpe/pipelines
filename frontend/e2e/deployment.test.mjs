// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { createHash, randomUUID } from 'node:crypto';
import { readFile, writeFile } from 'node:fs/promises';
import { test } from 'node:test';
import { chromium } from 'playwright';

const context = process.env.ARGO_CONTEXT || 'orbstack';
const namespace = process.env.ARGO_NAMESPACE || 'kfp-argo';
const origin = process.env.ARGO_UI_URL || process.env.KFP_TEST_HOST || 'http://127.0.0.1:3003';
const editor = process.env.ARGO_EDITOR_TOKEN,
  reader = process.env.ARGO_READER_TOKEN;
let versionName = process.env.ARGO_VERSION_NAME;
const encode = encodeURIComponent;
const workflowUrl = (name) => `/argo/api/v1/workflows/${namespace}/${encode(name)}`;
const kubectl = (args) =>
  execFileSync('kubectl', ['--context', context, '-n', namespace, ...args], {
    encoding: 'utf8',
    timeout: 180000,
  });
async function api(path, options = {}, token = editor) {
  const response = await fetch(origin + path, {
    ...options,
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
      ...options.headers,
    },
  });
  assert.ok(
    response.ok,
    `${options.method || 'GET'} ${path}: HTTP ${response.status}: ${await (response.ok ? Promise.resolve('') : response.text())}`,
  );
  return response;
}
async function json(path, options, token) {
  return (await api(path, options, token)).json();
}
async function waitFor(check, description, timeout = 180000) {
  const end = Date.now() + timeout;
  let last;
  while (Date.now() < end) {
    try {
      const result = await check();
      if (result) return result;
    } catch (error) {
      last = error;
    }
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  throw new Error(`Timed out: ${description}${last ? `: ${last.message}` : ''}`);
}
async function completed(name) {
  return waitFor(async () => {
    const run = await json(workflowUrl(name));
    assert.ok(
      !['Failed', 'Error'].includes(run.status?.phase),
      `Unexpected ${run.status?.phase}: ${name}`,
    );
    return run.status?.phase === 'Succeeded' && run;
  }, `workflow ${name}`);
}
const metadataPath = (run, node, archived = false) =>
  archived
    ? `/argo/artifact-files/${namespace}/archived-workflows/${run.metadata.uid}/${node.id}/outputs/kfp-metadata`
    : `/argo/artifacts/${namespace}/${run.metadata.name}/${node.id}/kfp-metadata`;
async function connect(page, token) {
  await page.getByLabel('Kubernetes bearer token').fill(token);
  await page.getByRole('button', { name: 'Connect', exact: true }).click();
  await page.getByRole('dialog').waitFor({ state: 'hidden' });
  await page.locator('#sideNav').waitFor();
}
async function go(page, path) {
  await page.evaluate((path) => {
    window.location.hash = path;
  }, path);
}
async function saveResponse(page, path, action) {
  const waiting = page.waitForResponse(
    (response) => response.url().includes(path) && response.request().method() === 'POST',
  );
  await action();
  const response = await waiting;
  assert.ok(response.ok(), `${path}: ${response.status()} ${await response.text()}`);
  return response.json();
}
async function choosePipeline(page, name) {
  await page.getByRole('button', { name: 'Choose', exact: true }).first().click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Filter pipelines', { exact: true }).fill(name);
  await dialog.getByTestId('table-row').filter({ hasText: name }).click();
  await dialog.getByRole('button', { name: 'Use this pipeline', exact: true }).click();
}
async function openTask(page, run, task) {
  await go(page, `/runs/details/${encode(run.metadata.uid)}`);
  await page.getByRole('button', { name: task, exact: true }).click();
  await page.getByRole('button', { name: 'Input/Output', exact: true }).waitFor();
}

test(
  'stock KFP presentation over the deployed native lifecycle and RBAC',
  { timeout: 720000 },
  async () => {
    assert.ok(
      editor && reader && versionName,
      'Set ARGO_EDITOR_TOKEN, ARGO_READER_TOKEN and ARGO_VERSION_NAME.',
    );
    const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome' });
    const page = await browser.newPage({ viewport: { width: 1500, height: 1100 } });
    const errors = [],
      paths = [],
      navigations = [];
    page.on('framenavigated', (frame) => {
      if (frame === page.mainFrame()) navigations.push(frame.url());
    });
    page.on('pageerror', (error) => errors.push(error.message));
    page.on('request', (request) => paths.push(new URL(request.url()).pathname));
    const report = { context, namespace, versionName };
    try {
      await page.goto(`${origin}/argo.html?namespace=${namespace}`);
      await connect(page, editor);
      // Give this verification pair private cache keys without clearing any existing run.
      const original = await json(`/argo/api/v1/workflow-templates/${namespace}/${versionName}`);
      const freshSpec = structuredClone(original.spec),
        salt = randomUUID();
      for (const template of freshSpec.templates)
        if (template.memoize) template.memoize.key = salt + '-' + template.memoize.key;
      delete freshSpec.workflowMetadata;
      const hash = createHash('sha256')
        .update(JSON.stringify(freshSpec))
        .digest('hex')
        .slice(0, 12);
      const labels = { ...original.metadata.labels, 'pipelines.kubeflow.org/version': hash };
      freshSpec.workflowMetadata = { labels };
      const fresh = {
        apiVersion: 'argoproj.io/v1alpha1',
        kind: 'WorkflowTemplate',
        metadata: {
          name: `verification-${hash}`,
          namespace,
          labels,
          annotations: original.metadata.annotations,
        },
        spec: freshSpec,
      };
      await page.locator('#pipelinesBtn').click();
      await page.getByRole('button', { name: 'Upload pipeline', exact: true }).click();
      await page.getByLabel('Pipeline Name', { exact: false }).fill(`verification-${hash}`);
      await page.locator('input[type=file]').setInputFiles({
        name: 'verification.yaml',
        mimeType: 'application/yaml',
        buffer: Buffer.from(JSON.stringify(fresh)),
      });
      const uploaded = await saveResponse(page, '/workflow-templates/', () =>
        page.getByRole('button', { name: 'Create', exact: true }).click(),
      );
      versionName = uploaded.metadata.name;
      report.versionName = versionName;
      await page.getByRole('button', { name: 'Show Summary', exact: true }).waitFor();
      await page.locator('#experimentsBtn').click();
      await page.getByRole('button', { name: 'Create experiment', exact: true }).click();
      const displayName = `Native training ${hash}`;
      await page.getByLabel('Experiment name', { exact: false }).fill(displayName);
      await page
        .getByLabel('Description', { exact: true })
        .fill('Native Argo end-to-end verification');
      const experiment = await saveResponse(page, '/configmaps', () =>
        page.getByRole('button', { name: 'Next', exact: true }).click(),
      );
      report.experiment = experiment.metadata.name;
      await choosePipeline(page, `verification-${hash}`);
      const submitted = [];
      for (const factor of ['1.0', '1.2']) {
        if (submitted.length)
          await go(
            page,
            `/runs/new?pipelineVersionId=${encode(versionName)}&experimentId=${encode(experiment.metadata.name)}`,
          );
        await page.getByLabel('Run name', { exact: false }).fill(`Native verify ${hash} ${factor}`);
        await page.getByLabel('factor', { exact: true }).fill(factor);
        const run = await saveResponse(page, `/workflows/${namespace}`, () =>
          page.getByRole('button', { name: 'Start', exact: true }).click(),
        );
        submitted.push(await completed(run.metadata.name));
      }
      report.runs = submitted.map((run) => ({ name: run.metadata.name, uid: run.metadata.uid }));
      const taskMetadata = [];
      for (const [index, run] of submitted.entries()) {
        const raw = JSON.parse(kubectl(['get', 'workflow', run.metadata.name, '-o', 'json']));
        assert.ok(raw.status.offloadNodeStatusVersion, 'Node status was not offloaded');
        assert.ok(!raw.status.nodes || Object.keys(raw.status.nodes).length === 0);
        const nodes = Object.values(run.status.nodes),
          prepare = nodes.find((node) => node.displayName === 'prepare');
        assert.equal(prepare.memoizationStatus.hit, Boolean(index));
        const metrics = await json(
          metadataPath(
            run,
            nodes.find((node) => node.displayName === 'evaluate'),
          ),
        );
        assert.equal(metrics.metrics.score, index ? 1 : 2 / 3);
        taskMetadata.push(await json(metadataPath(run, prepare)));
        const pods = JSON.parse(
          kubectl([
            'get',
            'pods',
            '-l',
            `workflows.argoproj.io/workflow=${run.metadata.name}`,
            '-o',
            'json',
          ]),
        );
        assert.equal(pods.items.length, index ? 2 : 3);
        for (const pod of pods.items) {
          assert.deepEqual(pod.spec.containers.map((container) => container.name).sort(), [
            'main',
            'wait',
          ]);
          const image = pod.spec.containers.find((container) => container.name === 'main').image;
          const digest = image.match(/:kfp-([0-9a-f]{64})$/)?.[1];
          assert.ok(digest, 'Component image was not a content-named snapshot');
          assert.ok(
            pod.status.containerStatuses
              .find((container) => container.name === 'main')
              .imageID.endsWith(digest),
            'Running image differs from its declared build identity',
          );
        }
      }
      assert.deepEqual(taskMetadata[0], taskMetadata[1], 'Cached producer metadata changed');
      await openTask(page, submitted[1], 'prepare');
      await page.getByRole('link', { name: 'system.Dataset@0.0.1', exact: true }).waitFor();
      const downloading = page.waitForEvent('download');
      await page.getByRole('button', { name: 'Download', exact: true }).click();
      assert.deepEqual(
        JSON.parse(await readFile(await (await downloading).path(), 'utf8')),
        [1, 2, 3, 4],
      );
      await page.getByRole('button', { name: 'Logs', exact: true }).click();
      await page.getByText(/reused cached outputs/).waitFor();
      await page.locator('#runsBtn').click();
      await page.getByLabel('Filter runs', { exact: true }).fill(`Native verify ${hash}`);
      for (const run of submitted)
        await page.locator(`[data-row-id="${run.metadata.uid}"] input[type=checkbox]`).check();
      await page.getByRole('button', { name: 'Compare runs', exact: true }).click();
      await page.getByText('evaluate / score', { exact: true }).waitFor();
      await page.getByRole('cell', { name: '1', exact: true }).waitFor();
      await page.getByRole('cell', { name: '0.6666666666666666', exact: true }).waitFor();
      await openTask(page, submitted[1], 'train');
      await page.getByRole('button', { name: 'Logs', exact: true }).click();
      await page
        .getByText(/Looking for component `train`/)
        .first()
        .waitFor();
      await page.screenshot({ path: '/tmp/kfp-argo-deployed-runs.png', fullPage: true });

      // Recurring runs are persistent CronWorkflows, not browser state.
      await go(
        page,
        `/runs/new?pipelineVersionId=${encode(versionName)}&experimentId=${encode(experiment.metadata.name)}&recurring=1`,
      );
      await page
        .getByLabel('Recurring run config name', { exact: false })
        .fill(`Native schedule ${hash}`);
      await page.getByRole('combobox', { name: /Trigger type/ }).click();
      await page.getByRole('option', { name: 'Cron', exact: true }).click();
      await page.getByRole('checkbox', { name: /Allow editing cron expression/ }).check();
      await page.getByLabel('cron expression', { exact: true }).fill('0 9 * * *');
      const cron = await saveResponse(page, '/cron-workflows/', () =>
        page.getByRole('button', { name: 'Start', exact: true }).click(),
      );
      assert.equal(Boolean(cron.spec.suspend), false);
      assert.deepEqual(cron.spec.schedules, ['0 9 * * *']);
      report.schedule = cron.metadata.name;
      await page.waitForURL(/#\/recurringrun\/details\//);
      await page.getByRole('button', { name: 'Disable', exact: true }).click();
      await page.getByRole('button', { name: 'Enable', exact: true }).waitFor();
      await waitFor(
        async () =>
          (await json(`/argo/api/v1/cron-workflows/${namespace}/${cron.metadata.name}`)).spec
            .suspend === true,
        'schedule explicitly disabled after default-enabled creation',
      );
      await page.reload();
      await connect(page, editor);
      await page.getByText('Native schedule ' + hash, { exact: true }).waitFor();
      kubectl([
        'patch',
        'cronworkflow',
        cron.metadata.name,
        '--type=merge',
        '-p',
        JSON.stringify({ spec: { schedules: ['0 10 * * *'] } }),
      ]);
      await page.getByRole('button', { name: 'Refresh', exact: true }).click();
      await page
        .getByText(/0 10 \* \* \*/)
        .first()
        .waitFor();

      // Add a native approval gate without introducing any KFP controller.
      const version = await json(`/argo/api/v1/workflow-templates/${namespace}/${versionName}`);
      const spec = structuredClone(version.spec);
      delete spec.workflowMetadata;
      const root = spec.templates.find((template) => template.name === spec.entrypoint);
      root.dag.tasks.push({
        name: 'approval',
        template: 'native-approval',
        dependencies: ['train'],
      });
      root.dag.tasks.find((task) => task.name === 'evaluate').dependencies.push('approval');
      spec.templates.push({ name: 'native-approval', suspend: {} });
      const gate = await json(`/argo/api/v1/workflows/${namespace}`, {
        method: 'POST',
        body: JSON.stringify({
          namespace,
          workflow: {
            apiVersion: 'argoproj.io/v1alpha1',
            kind: 'Workflow',
            metadata: {
              generateName: 'native-approval-',
              labels: { 'pipelines.kubeflow.org/pipeline': 'native-approval' },
            },
            spec,
          },
        }),
      });
      report.approval = gate.metadata.name;
      await waitFor(
        async () =>
          Object.values((await json(workflowUrl(gate.metadata.name))).status?.nodes || {}).some(
            (node) => node.type === 'Suspend' && node.phase === 'Running',
          ),
        'approval gate',
      );
      await page.reload();
      await connect(page, reader);
      await openTask(page, gate, 'approval');
      await page.getByRole('button', { name: 'Resume', exact: true }).click();
      await page
        .getByText(/Argo request failed \(403\)/)
        .first()
        .waitFor();
      assert.equal((await json(workflowUrl(gate.metadata.name))).status.phase, 'Running');
      await page.getByRole('button', { name: 'OK', exact: true }).click();
      await page.locator('#experimentsBtn').click();
      await page.getByRole('button', { name: 'Create experiment', exact: true }).click();
      await page.getByLabel('Experiment name', { exact: false }).fill('Denied experiment');
      await page.getByRole('button', { name: 'Next', exact: true }).click();
      await page
        .getByText(/Argo request failed \(403\)/)
        .first()
        .waitFor();
      await page.screenshot({ path: '/tmp/kfp-argo-denied.png', fullPage: true });
      await page.reload();
      await connect(page, editor);
      await openTask(page, gate, 'approval');
      await page.getByRole('button', { name: 'Resume', exact: true }).click();
      await completed(gate.metadata.name);

      // Stock archival is logical and reversible; engine GC is a separate event.
      const first = submitted[0],
        archivePath = `/argo/api/v1/archived-workflows/${first.metadata.uid}?namespace=${namespace}`;
      await waitFor(
        async () => (await json(archivePath)).metadata.uid === first.metadata.uid,
        'workflow archive',
      );
      await go(page, `/runs/details/${first.metadata.uid}`);
      await page.getByRole('button', { name: 'Archive', exact: true }).click();
      await page.getByRole('button', { name: 'Confirm', exact: true }).click();
      await page.waitForURL(/#\/archive\/runs/);
      assert.equal(
        (
          await json(
            `/kubernetes/api/v1/namespaces/${namespace}/configmaps/run-${first.metadata.uid}`,
          )
        ).data.storageState,
        'ARCHIVED',
      );
      assert.equal(
        (
          await json(
            `/kubernetes/apis/argoproj.io/v1alpha1/namespaces/${namespace}/workflows/${first.metadata.name}`,
          )
        ).metadata.uid,
        first.metadata.uid,
      );
      // Simulate subsequent controller TTL/GC only for this test-owned workflow.
      kubectl(['delete', 'workflow', first.metadata.name]);
      const archived = await json(archivePath),
        prepared = Object.values(archived.status.nodes).find(
          (node) => node.displayName === 'prepare',
        );
      assert.deepEqual(await json(metadataPath(archived, prepared, true)), taskMetadata[0]);
      await openTask(page, first, 'prepare');
      await page.getByRole('link', { name: 'system.Dataset@0.0.1', exact: true }).waitFor();
      await page.getByRole('button', { name: 'Logs', exact: true }).click();
      await page
        .getByText(/Looking for component `prepare`/)
        .first()
        .waitFor();
      await page.screenshot({ path: '/tmp/kfp-argo-archived.png', fullPage: true });
      const listed = (await json(`/argo/api/v1/archived-workflows?namespace=${namespace}`)).items;
      assert.equal(listed.filter((run) => run.metadata.uid === first.metadata.uid).length, 1);

      // Group deletion remains a native API operation; the stock UI has no Delete experiment button.
      await api(
        `/kubernetes/api/v1/namespaces/${namespace}/configmaps/${experiment.metadata.name}`,
        {
          method: 'DELETE',
          body: JSON.stringify({
            apiVersion: 'v1',
            kind: 'DeleteOptions',
            preconditions: { uid: experiment.metadata.uid },
          }),
        },
      );
      report.experimentDeletion = 'native Kubernetes API, UID-preconditioned';
      await waitFor(
        async () =>
          !(
            await json(
              `/kubernetes/api/v1/namespaces/${namespace}/configmaps?labelSelector=pipelines.kubeflow.org%2Fresource%3Dexperiment`,
            )
          ).items.some((item) => item.metadata.uid === experiment.metadata.uid),
        'experiment deletion',
      );
      assert.equal(
        (await json(workflowUrl(submitted[1].metadata.name))).metadata.uid,
        submitted[1].metadata.uid,
      );
      assert.equal((await json(archivePath)).metadata.uid, first.metadata.uid);
      assert.equal(
        (await json(`/argo/api/v1/cron-workflows/${namespace}/${cron.metadata.name}`)).metadata.uid,
        cron.metadata.uid,
      );

      // Archive and cached payloads live on PVCs, independently of application restarts.
      kubectl(['rollout', 'restart', 'deployment/minio', 'deployment/postgres']);
      kubectl(['rollout', 'status', 'deployment/minio', '--timeout=180s']);
      kubectl(['rollout', 'status', 'deployment/postgres', '--timeout=180s']);
      // Argo 4.1.6 can retain a closed SQL session after a database restart. This is
      // a persistence check across a full stack restart, not an HA/reconnect claim.
      kubectl(['rollout', 'restart', 'deployment/argo-server', 'deployment/workflow-controller']);
      kubectl(['rollout', 'status', 'deployment/argo-server', '--timeout=180s']);
      kubectl(['rollout', 'status', 'deployment/workflow-controller', '--timeout=180s']);
      report.storageRestartRecovery = 'Argo Server and workflow controller explicitly restarted';
      await waitFor(
        async () => (await json(archivePath)).metadata.uid === first.metadata.uid,
        'persistent SQL archive after full stack restart',
      );
      await waitFor(async () => {
        assert.deepEqual(await json(metadataPath(archived, prepared, true)), taskMetadata[0]);
        assert.deepEqual(
          await json(
            `/argo/artifact-files/${namespace}/archived-workflows/${first.metadata.uid}/${prepared.id}/outputs/dataset`,
          ),
          [1, 2, 3, 4],
        );
        return true;
      }, 'persistent artifact metadata and payload after full stack restart');
      assert.deepEqual(errors, []);
      assert.ok(
        !paths.some((path) => /^\/(apis|api|system|k8s)\//.test(path)),
        'Unexpected KFP backend request',
      );
      assert.deepEqual(
        JSON.parse(kubectl(['get', 'deployments', '-o', 'json']))
          .items.map((item) => item.metadata.name)
          .sort(),
        ['argo-server', 'kfp-argo-ui', 'minio', 'postgres', 'workflow-controller'],
      );
      report.result = 'passed';
      await writeFile('/tmp/kfp-argo-deployment-evidence.json', JSON.stringify(report, null, 2));
    } catch (error) {
      await page
        .screenshot({ path: '/tmp/kfp-argo-e2e-failure.png', fullPage: true })
        .catch(() => {});
      await writeFile(
        '/tmp/kfp-argo-e2e-failure.txt',
        await page.locator('body').innerText(),
      ).catch(() => {});
      await writeFile(
        '/tmp/kfp-argo-partial-evidence.json',
        JSON.stringify({ ...report, errors, navigations }, null, 2),
      );
      throw error;
    } finally {
      await browser.close();
    }
  },
);
