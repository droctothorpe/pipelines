// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  editor,
  failures,
  fixture,
  json,
  launch,
  namespace,
  nodeNamed,
  open,
  requireTokens,
  waitForPhase,
} from './live.mjs';

test(
  'the run form submits an artifact-list version with init-only repository bindings',
  { timeout: 900000 },
  async () => {
    requireTokens();
    const version = await fixture('artifact-list-version');
    const { browser, page, errors, paths } = await launch();
    try {
      await open(
        page,
        `/runs/new?pipelineVersionId=${version.version_id}&experimentId=${version.experiment_id}`,
        editor,
      );
      await page
        .getByLabel('Run name', { exact: false })
        .fill('UI artifact-list staging ' + Date.now());
      await page.getByLabel(/^values/).fill('[3,4]');
      await page.getByLabel(/^nonce/).fill('UI-' + Date.now());
      await page.getByLabel(/^directory/).fill('false');
      const submission = page.waitForResponse(
        (r) =>
          r.request().method() === 'POST' &&
          new URL(r.url()).pathname === `/argo/api/v1/workflows/${namespace}`,
      );
      await page.getByRole('button', { name: 'Start', exact: true }).click();
      const response = await submission;
      assert.ok(response.ok());
      const run = await response.json();
      const template = run.spec.templates.find((t) =>
        t.initContainers?.some((c) => c.name === 'kfp-stage-artifacts'),
      );
      const secretVolumes = template.volumes.filter((v) => v.secret).map((v) => v.name);
      assert.ok(secretVolumes.length);
      assert.ok(template.container.volumeMounts.every((v) => !secretVolumes.includes(v.name)));
      assert.ok(
        !paths.some((path) => path.includes('/secrets/')),
        'The browser must never read secrets',
      );
      const completed = await waitForPhase(run.metadata.name);
      assert.equal(completed.status.phase, 'Succeeded', JSON.stringify(failures(completed)));
      assert.equal(
        nodeNamed(completed, 'consume').outputs.parameters.find((p) => p.name === 'Output').value,
        '7',
      );
      const versions = await json(`/argo/api/v1/workflow-templates/${namespace}`);
      const stored = versions.items.find((v) => v.metadata.uid === version.version_id);
      const original = stored.spec.templates.find((t) =>
        t.initContainers?.some((c) => c.name === 'kfp-stage-artifacts'),
      );
      assert.equal(
        original.initContainers
          .find((c) => c.name === 'kfp-stage-artifacts')
          .env.find((e) => e.name === 'KFP_STAGING_REPOSITORY').value,
        '{}',
        'The stored version must stay free of repository bindings',
      );
      assert.deepEqual(errors, []);
    } finally {
      await browser.close();
    }
  },
);
