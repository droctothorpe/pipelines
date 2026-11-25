// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { editor, fixture, go, launch, namespace, open, requireTokens, sdk } from './live.mjs';

test(
  'SDK-created identities and archive state work through the stock UI',
  { timeout: 900000 },
  async () => {
    requireTokens();
    const f = await fixture('interop');
    const { browser, page, errors } = await launch({ width: 1500, height: 1000 });
    try {
      await open(page, `/experiments/details/${f.experiment_id}`, editor);
      await page.getByTestId('page-title').filter({ hasText: f.experiment_name }).waitFor();
      await page.getByRole('link', { name: f.run_name, exact: true }).waitFor();
      await go(page, `/pipelines/details/${f.pipeline_id}/version/${f.version_id}`);
      await page.getByRole('button', { name: 'Show Summary', exact: true }).waitFor();
      await page.getByRole('button', { name: 'echo', exact: true }).waitFor();
      await go(page, `/runs/new?pipelineVersionId=${f.version_id}&experimentId=${f.experiment_id}`);
      await page.getByLabel('Run name', { exact: false }).fill(`UI custom root ${f.run_id}`);
      await page.getByLabel('Custom Pipeline Root', { exact: true }).check();
      // A prefix inside the bucket the namespace repository serves.
      const customRoot = `${f.artifact_root}/ui-root-${f.run_id}`;
      await page.getByRole('textbox', { name: /^Pipeline Root/ }).fill(customRoot);
      await page.getByLabel('value', { exact: true }).fill(`UI root ${f.run_id}`);
      const submission = page.waitForResponse(
        (r) =>
          r.request().method() === 'POST' &&
          r.url().endsWith(`/argo/api/v1/workflows/${namespace}`),
      );
      await page.getByRole('button', { name: 'Start', exact: true }).click();
      const submitted = await (await submission).json();
      await page.waitForURL(/#\/runs\/details\//);
      assert.equal(
        sdk(
          `r=c.wait_for_run_completion('${submitted.metadata.uid}',timeout=600); assert r.state=='SUCCEEDED',r.to_dict(); assert r.pipeline_version_id=='${f.version_id}'; print(r.runtime_config.pipeline_root)`,
        ),
        customRoot,
      );
      const sdkSchedule = JSON.parse(
        sdk(
          `import datetime,json; start=(datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(days=1)).replace(second=0,microsecond=0); end=start+datetime.timedelta(days=1); s=c.create_recurring_run(job_name='SDK trigger ${f.run_id}',pipeline_id='${f.pipeline_id}',version_id='${f.version_id}',experiment_id='${f.experiment_id}',namespace='${namespace}',interval_second=7,max_concurrency=3,no_catchup=True,enabled=False,start_time=start.isoformat(),end_time=end.isoformat(),params={'value':'schedule clone'},pipeline_root='${customRoot}'); print(json.dumps({'id':s.recurring_run_id,'start':start.isoformat(),'end':end.isoformat()}))`,
        ),
      );
      await go(page, `/runs/new?recurring=1&cloneFromRecurringRun=${sdkSchedule.id}`);
      await page
        .getByLabel('Maximum concurrent runs', { exact: false })
        .and(page.locator('input[value="3"]'))
        .waitFor();
      assert.equal(
        await page.getByLabel('Maximum concurrent runs', { exact: false }).inputValue(),
        '3',
      );
      assert.equal(
        await page.getByRole('checkbox', { name: 'Catchup', exact: true }).isChecked(),
        false,
      );
      assert.equal(
        await page.getByRole('textbox', { name: /^Pipeline Root/ }).inputValue(),
        customRoot,
      );
      await page
        .getByLabel('Recurring run config name', { exact: false })
        .fill(`UI schedule clone ${f.run_id}`);
      const scheduleSubmission = page.waitForResponse(
        (r) =>
          r.request().method() === 'POST' &&
          r.url().endsWith(`/argo/api/v1/cron-workflows/${namespace}`),
      );
      await page.getByRole('button', { name: 'Start', exact: true }).click();
      const uiSchedule = await (await scheduleSubmission).json();
      try {
        assert.deepEqual(uiSchedule.spec.schedules, ['@every 7s']);
        assert.equal(Boolean(uiSchedule.spec.suspend), false);
        assert.equal(uiSchedule.spec.workflowSpec.synchronization.semaphores.length, 1);
        sdk(
          `s=c.get_recurring_run('${uiSchedule.metadata.uid}'); assert s.max_concurrency=='3'; assert s.no_catchup is True; assert s.trigger.periodic_schedule.interval_second=='7'; assert s.trigger.periodic_schedule.start_time.isoformat()=='${sdkSchedule.start}'; assert s.trigger.periodic_schedule.end_time.isoformat()=='${sdkSchedule.end}'; assert s.runtime_config.pipeline_root=='${customRoot}'; assert s.runtime_config.parameters=={'value':'schedule clone'}`,
        );
        // C31/C36: the list shows the schedule window and links the experiment.
        // The form navigates to the new schedule once the response lands.
        await page.waitForURL(/#\/recurringrun\/details\//);
        await go(page, '/recurringruns');
        await page
          .getByLabel('Filter recurring runs', { exact: true })
          .fill(`UI schedule clone ${f.run_id}`);
        const scheduleRow = page.locator(`[data-row-id="${uiSchedule.metadata.name}"]`);
        await scheduleRow.waitFor();
        const expectedStart = await page.evaluate(
          (iso) => new Date(iso).toLocaleString(),
          sdkSchedule.start,
        );
        assert.ok(
          (await scheduleRow.innerText()).includes(expectedStart),
          'Recurring run list shows the start time',
        );
        await scheduleRow.getByRole('link', { name: f.experiment_name, exact: true }).waitFor();
      } finally {
        sdk(`c.disable_recurring_run('${uiSchedule.metadata.uid}')`);
      }
      sdk(`c.archive_run('${f.run_id}')`);
      await go(page, '/archive/runs');
      await page.getByLabel('Filter runs', { exact: true }).fill(f.run_name);
      await page.getByRole('link', { name: f.run_name, exact: true }).waitFor();
      await page.locator(`[data-row-id="${f.run_id}"] input[type=checkbox]`).check();
      const restored = page.waitForResponse(
        (r) => r.request().method() === 'PUT' && r.url().includes('/configmaps/run-'),
      );
      await page.getByRole('button', { name: 'Restore', exact: true }).click();
      assert.ok((await restored).ok());
      assert.equal(sdk(`print(c.get_run('${f.run_id}').storage_state)`), 'AVAILABLE');
      await go(page, `/runs/details/${f.run_id}`);
      await page.getByRole('button', { name: 'Archive', exact: true }).click();
      await page.getByRole('button', { name: 'Confirm', exact: true }).click();
      await page.waitForURL(/#\/archive\/runs/);
      assert.equal(sdk(`print(c.get_run('${f.run_id}').storage_state)`), 'ARCHIVED');
      await go(page, `/experiments/details/${f.experiment_id}`);
      await page.getByRole('button', { name: 'Archive', exact: true }).click();
      await page.getByRole('button', { name: 'Confirm', exact: true }).click();
      await page.getByRole('dialog').waitFor({ state: 'hidden' });
      assert.equal(
        sdk(`print(c.get_experiment(experiment_id='${f.experiment_id}').storage_state)`),
        'ARCHIVED',
      );
      sdk(`c.unarchive_experiment('${f.experiment_id}')`);
      await page.locator('#experimentsBtn').click();
      await page.getByRole('link', { name: f.experiment_name, exact: true }).waitFor();
      await page.locator('#pipelinesBtn').click();
      await page.getByRole('button', { name: 'Upload pipeline', exact: true }).click();
      const uiName = `UI pipeline ${f.run_id}`;
      await page.getByLabel('Pipeline Name', { exact: false }).fill(uiName);
      const packageData = {
        apiVersion: 'argoproj.io/v1alpha1',
        kind: 'WorkflowTemplate',
        metadata: {
          name: 'ui-template',
          labels: { 'pipelines.kubeflow.org/pipeline': 'ui-template' },
        },
        spec: {
          entrypoint: 'main',
          templates: [
            { name: 'main', container: { image: 'busybox:1.36', command: ['echo', 'hello'] } },
          ],
        },
      };
      await page.locator('input[type=file]').setInputFiles({
        name: 'pipeline.yaml',
        mimeType: 'application/yaml',
        buffer: Buffer.from(JSON.stringify(packageData)),
      });
      await page.getByRole('button', { name: 'Create', exact: true }).click();
      await page.waitForURL(/#\/pipelines\/details\//);
      assert.ok(
        sdk(
          `p=c.get_pipeline_id(${JSON.stringify(uiName)}); assert p; assert len(c.list_pipeline_versions(p).pipeline_versions)==1; print(p)`,
        ),
      );
      assert.deepEqual(errors, []);
    } finally {
      await browser.close();
    }
  },
);
