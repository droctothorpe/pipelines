// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';
import { chromium } from 'playwright';

const root = fileURLToPath(new URL('../../', import.meta.url));
const origin = process.env.ARGO_UI_URL || 'http://127.0.0.1:3003';
const namespace = process.env.ARGO_NAMESPACE || 'kfp-argo';
const python = (args) => execFileSync('uv', ['run', '--python', '3.11', '--isolated', '--frozen', '--extra', 'test', 'python', ...args], { cwd: root, encoding: 'utf8', timeout: 700000 });
const clientCode = `import os,kfp; c=kfp.Client(host=os.environ.get('ARGO_UI_URL','http://127.0.0.1:3003'),namespace=os.environ.get('ARGO_NAMESPACE','kfp-argo'),existing_token=os.environ['ARGO_EDITOR_TOKEN']); `;
const sdk = (code) => python(['-c', clientCode + code]).trim();

test('SDK-created identities and archive state work through the stock UI', { timeout: 900000 }, async () => {
  assert.ok(process.env.ARGO_EDITOR_TOKEN, 'Set ARGO_EDITOR_TOKEN for the test namespace.');
  const temporary = await mkdtemp(join(tmpdir(), 'kfp-sdk-ui-'));
  const fixturePath = join(temporary, 'resources.json');
  let browser;
  try {
    python(['test/e2e/pipelines/ui_interop.py', fixturePath]);
    const fixture = JSON.parse(await readFile(fixturePath, 'utf8'));
    browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome' });
    const page = await browser.newPage({ viewport: { width: 1500, height: 1000 } });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const go = path => page.evaluate(path => { window.location.hash = path; }, path);
    await page.goto(`${origin}/argo.html?namespace=${namespace}#/experiments/details/${fixture.experiment_id}`);
    await page.getByLabel('Kubernetes bearer token').fill(process.env.ARGO_EDITOR_TOKEN);
    await page.getByRole('button', { name: 'Connect', exact: true }).click();
    await page.getByRole('dialog').waitFor({ state: 'hidden' });
    await page.getByTestId('page-title').filter({ hasText: fixture.experiment_name }).waitFor();
    await page.getByRole('link', { name: fixture.run_name, exact: true }).waitFor();
    await go(`/pipelines/details/${fixture.pipeline_id}/version/${fixture.version_id}`);
    await page.getByRole('button', { name: 'Show Summary', exact: true }).waitFor();
    await page.getByRole('button', { name: 'echo', exact: true }).waitFor();
    await go(`/runs/new?pipelineVersionId=${fixture.version_id}&experimentId=${fixture.experiment_id}`);
    await page.getByLabel('Run name', { exact: false }).fill(`UI custom root ${fixture.run_id}`);
    await page.getByLabel('Custom Pipeline Root', { exact: true }).check();
    const customRoot = `s3://argo-artifacts/ui-root-${fixture.run_id}`;
    await page.getByRole('textbox', { name: /^Pipeline Root/ }).fill(customRoot);
    await page.getByLabel('value', { exact: true }).fill(`UI root ${fixture.run_id}`);
    const submission = page.waitForResponse(response => response.request().method() === 'POST' && response.url().endsWith(`/argo/api/v1/workflows/${namespace}`));
    await page.getByRole('button', { name: 'Start', exact: true }).click();
    const submittedResponse = await submission;
    assert.ok(submittedResponse.ok());
    const submitted = await submittedResponse.json();
    await page.waitForURL(/#\/runs\/details\//);
    assert.equal(sdk(`r=c.wait_for_run_completion('${submitted.metadata.uid}',timeout=600); assert r.state=='SUCCEEDED',r.to_dict(); assert r.pipeline_version_id=='${fixture.version_id}'; print(r.runtime_config.pipeline_root)`), customRoot);
    const sdkSchedule = JSON.parse(sdk(`import datetime,json; start=(datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(days=1)).replace(second=0,microsecond=0); end=start+datetime.timedelta(days=1); s=c.create_recurring_run(job_name='SDK trigger ${fixture.run_id}',pipeline_id='${fixture.pipeline_id}',version_id='${fixture.version_id}',experiment_id='${fixture.experiment_id}',namespace='${namespace}',interval_second=7,max_concurrency=3,no_catchup=True,enabled=False,start_time=start.isoformat(),end_time=end.isoformat(),params={'value':'schedule clone'},pipeline_root='${customRoot}'); print(json.dumps({'id':s.recurring_run_id,'start':start.isoformat(),'end':end.isoformat()}))`));
    await go(`/runs/new?recurring=1&cloneFromRecurringRun=${sdkSchedule.id}`);
    await page.getByLabel('Maximum concurrent runs', {exact:false}).and(page.locator('input[value="3"]')).waitFor();
    assert.equal(await page.getByLabel('Maximum concurrent runs', {exact:false}).inputValue(), '3');
    assert.equal(await page.getByRole('checkbox', {name:'Catchup',exact:true}).isChecked(), false);
    assert.equal(await page.getByRole('textbox', {name:/^Pipeline Root/}).inputValue(), customRoot);
    await page.getByLabel('Recurring run config name', {exact:false}).fill(`UI schedule clone ${fixture.run_id}`);
    const scheduleSubmission = page.waitForResponse(response => response.request().method()==='POST' && response.url().endsWith(`/argo/api/v1/cron-workflows/${namespace}`));
    await page.getByRole('button', {name:'Start',exact:true}).click();
    const scheduleResponse = await scheduleSubmission;
    assert.ok(scheduleResponse.ok());
    const uiSchedule = await scheduleResponse.json();
    try {
      assert.deepEqual(uiSchedule.spec.schedules,['@every 7s']);
      assert.equal(Boolean(uiSchedule.spec.suspend),false);
      assert.equal(uiSchedule.spec.workflowSpec.synchronization.semaphores.length,1);
      sdk(`s=c.get_recurring_run('${uiSchedule.metadata.uid}'); assert s.max_concurrency=='3'; assert s.no_catchup is True; assert s.trigger.periodic_schedule.interval_second=='7'; assert s.trigger.periodic_schedule.start_time.isoformat()=='${sdkSchedule.start}'; assert s.trigger.periodic_schedule.end_time.isoformat()=='${sdkSchedule.end}'; assert s.runtime_config.pipeline_root=='${customRoot}'; assert s.runtime_config.parameters=={'value':'schedule clone'}`);
    } finally {
      sdk(`c.disable_recurring_run('${uiSchedule.metadata.uid}')`);
    }
    sdk(`c.archive_run('${fixture.run_id}')`);
    await go('/archive/runs');
    await page.getByLabel('Filter runs', { exact: true }).fill(fixture.run_name);
    await page.getByRole('link', { name: fixture.run_name, exact: true }).waitFor();
    await page.locator(`[data-row-id="${fixture.run_id}"] input[type=checkbox]`).check();
    const restored = page.waitForResponse(response => response.request().method() === 'PUT' && response.url().includes('/configmaps/run-'));
    await page.getByRole('button', { name: 'Restore', exact: true }).click();
    assert.ok((await restored).ok());
    assert.equal(sdk(`print(c.get_run('${fixture.run_id}').storage_state)`), 'AVAILABLE');
    await go(`/runs/details/${fixture.run_id}`);
    await page.getByRole('button', { name: 'Archive', exact: true }).click();
    await page.getByRole('button', { name: 'Confirm', exact: true }).click();
    await page.waitForURL(/#\/archive\/runs/);
    assert.equal(sdk(`print(c.get_run('${fixture.run_id}').storage_state)`), 'ARCHIVED');
    await go(`/experiments/details/${fixture.experiment_id}`);
    await page.getByRole('button', { name: 'Archive', exact: true }).click();
    await page.getByRole('button', { name: 'Confirm', exact: true }).click();
    await page.getByRole('dialog').waitFor({ state: 'hidden' });
    assert.equal(sdk(`print(c.get_experiment(experiment_id='${fixture.experiment_id}').storage_state)`), 'ARCHIVED');
    sdk(`c.unarchive_experiment('${fixture.experiment_id}')`);
    await page.locator('#experimentsBtn').click();
    await page.getByRole('link', { name: fixture.experiment_name, exact: true }).waitFor();
    await page.locator('#pipelinesBtn').click();
    await page.getByRole('button', { name: 'Upload pipeline', exact: true }).click();
    const uiName = `UI pipeline ${fixture.run_id}`;
    await page.getByLabel('Pipeline Name', { exact: false }).fill(uiName);
    const packageData = { apiVersion: 'argoproj.io/v1alpha1', kind: 'WorkflowTemplate', metadata: { name: 'ui-template', labels: { 'pipelines.kubeflow.org/pipeline': 'ui-template' } }, spec: { entrypoint: 'main', templates: [{ name: 'main', container: { image: 'busybox:1.36', command: ['echo', 'hello'] } }] } };
    await page.locator('input[type=file]').setInputFiles({ name: 'pipeline.yaml', mimeType: 'application/yaml', buffer: Buffer.from(JSON.stringify(packageData)) });
    await page.getByRole('button', { name: 'Create', exact: true }).click();
    await page.waitForURL(/#\/pipelines\/details\//);
    const uploadedId = sdk(`p=c.get_pipeline_id(${JSON.stringify(uiName)}); assert p; assert len(c.list_pipeline_versions(p).pipeline_versions)==1; print(p)`);
    assert.ok(uploadedId);
    assert.deepEqual(errors, []);
    console.log(`Verified SDK/UI identities and bidirectional archive/restore for ${fixture.run_id}.`);
  } finally {
    await browser?.close();
    await rm(temporary, { recursive: true, force: true });
  }
});
