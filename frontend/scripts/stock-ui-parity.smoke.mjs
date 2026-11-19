// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
// Optional reference check: supply a served, unmodified stock frontend build.
import assert from 'node:assert/strict';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { test } from 'node:test';
import { chromium } from 'playwright';
const reference = process.env.KFP_STOCK_UI_URL;
const output = process.env.KFP_PARITY_OUTPUT || '/tmp/kfp-stock-ui-parity';
const pages = [
  ['pipelines', 'No pipelines found. Click "Upload pipeline" to start.'],
  ['runs', 'No available runs found.'],
  ['experiments', 'No experiments found. Click "Create experiment" to start.'],
  ['recurringRuns', 'No available recurring runs found.'],
  ['artifacts', 'No artifacts found.'],
];
test(
  'stock and native list presentation match at desktop and mobile sizes',
  { skip: !reference, timeout: 120000 },
  async () => {
    await mkdir(output, { recursive: true });
    const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || undefined });
    const report = [];
    try {
      for (const viewport of [
        { width: 1280, height: 720 },
        { width: 390, height: 844 },
      ]) {
        const captures = {};
        for (const mode of ['stock', 'native']) {
          const page = await browser.newPage({ viewport });
          const errors = [];
          page.on('pageerror', (error) => errors.push(error.message));
          await page.route('**/*', async (route) => {
            const url = new URL(route.request().url());
            if (
              mode === 'stock' &&
              (url.pathname === '/' ||
                url.pathname.startsWith('/static/') ||
                url.pathname.endsWith('.html'))
            )
              return route.continue();
            if (
              mode === 'native' &&
              (url.pathname.endsWith('.html') || url.pathname.startsWith('/static/'))
            ) {
              const type = url.pathname.endsWith('.js')
                ? 'text/javascript'
                : url.pathname.endsWith('.css')
                  ? 'text/css'
                  : url.pathname.endsWith('.png')
                    ? 'image/png'
                    : 'text/html';
              return route.fulfill({
                contentType: type,
                body: await readFile(new URL('../build' + url.pathname, import.meta.url)),
              });
            }
            if (url.pathname.startsWith('/system/'))
              return route.fulfill({ contentType: 'text/plain', body: '' });
            return route.fulfill({
              contentType: 'application/json',
              body: JSON.stringify({
                items: [],
                pipelines: [],
                experiments: [],
                runs: [],
                recurring_runs: [],
                artifacts: [],
              }),
            });
          });
          await page.goto(
            mode === 'stock'
              ? `${reference}/#/pipelines`
              : 'http://localhost/argo.html?namespace=team#/pipelines',
          );
          if (mode === 'native') {
            await page.getByLabel('Kubernetes bearer token').fill('fixture-only');
            await page.getByRole('button', { name: 'Connect', exact: true }).click();
            await page.getByRole('dialog').waitFor({ state: 'hidden' });
          }
          captures[mode] = {};
          for (const [id, empty] of pages) {
            await page.locator(`#${id}Btn`).click();
            await page.getByText(empty, { exact: true }).waitFor();
            await page.waitForFunction(
              (width) => document.querySelector('#sideNav').getBoundingClientRect().width === width,
              viewport.width > 960 ? 220 : 72,
            );
            await page.mouse.move(0, 0);
            await page.waitForTimeout(350);
            const image = await page.screenshot({
              path: `${output}/${mode}-${viewport.width}-${id}.png`,
            });
            captures[mode][id] = image.toString('base64');
          }
          assert.deepEqual(errors, []);
          await page.close();
        }
        const decoder = await browser.newPage();
        for (const [id] of pages) {
          const difference = await decoder.evaluate(
            async ([a, b]) => {
              const pixels = async (base64) => {
                const image = new Image();
                image.src = 'data:image/png;base64,' + base64;
                await image.decode();
                const canvas = document.createElement('canvas');
                canvas.width = image.width;
                canvas.height = image.height;
                const ctx = canvas.getContext('2d');
                ctx.drawImage(image, 0, 0);
                return ctx.getImageData(0, 0, canvas.width, canvas.height).data;
              };
              const left = await pixels(a),
                right = await pixels(b);
              let count = 0;
              for (let i = 0; i < left.length; i += 4)
                if (
                  Math.max(
                    Math.abs(left[i] - right[i]),
                    Math.abs(left[i + 1] - right[i + 1]),
                    Math.abs(left[i + 2] - right[i + 2]),
                  ) > 20
                )
                  count++;
              return count;
            },
            [captures.stock[id], captures.native[id]],
          );
          report.push({ viewport, page: id, differingPixels: difference });
        }
        await decoder.close();
      }
      await writeFile(`${output}/report.json`, JSON.stringify(report, null, 2));
      assert.deepEqual(
        report.filter((row) => row.differingPixels > 0),
        [],
        `Visual differences; see ${output}`,
      );
    } finally {
      await browser.close();
    }
  },
);
