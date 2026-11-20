// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { test } from 'node:test';
import { chromium } from 'playwright';

const origin = process.env.ARGO_UI_URL || 'http://127.0.0.1:3014';
const namespace = process.env.ARGO_NAMESPACE || 'kfp-argo';
const uid = process.env.ARGO_PREVIEW_RUN_ID;
const token = process.env.ARGO_EDITOR_TOKEN;
const output = process.env.ARGO_PREVIEW_EVIDENCE || '/tmp/kfp-preview-ui-evidence';

test('stock dataset/model viewers display native sibling previews without loading payloads', {timeout:120000}, async () => {
  assert.ok(uid && token, 'Set ARGO_PREVIEW_RUN_ID and ARGO_EDITOR_TOKEN.');
  const response = await fetch(`${origin}/argo/api/v1/archived-workflows/${uid}?namespace=${namespace}`, {headers:{Authorization:`Bearer ${token}`}});
  assert.ok(response.ok, `Archive request: ${response.status}`);
  const run = await response.json();
  const node = Object.values(run.status.nodes).find(node => node.outputs?.artifacts?.some(artifact => artifact.name==='dataset-preview'));
  assert.ok(node, 'The run must contain an uploaded dataset preview.');
  const browser = await chromium.launch({channel:process.env.PLAYWRIGHT_CHANNEL || 'chrome'});
  try {
    const page = await browser.newPage({viewport:{width:1280,height:720}});
    const requests=[], errors=[];
    page.on('request', request => requests.push(new URL(request.url()).pathname));
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(`${origin}/argo.html?namespace=${namespace}#/artifacts/${uid}/${encodeURIComponent(node.id)}/dataset`);
    await page.getByLabel('Kubernetes bearer token').fill(token);
    await page.getByRole('button',{name:'Connect',exact:true}).click();
    await page.getByRole('dialog').waitFor({state:'hidden'});
    await page.getByRole('button',{name:'Visualization',exact:true}).click();
    await page.getByRole('table',{name:'Dataset sample'}).waitFor();
    await page.getByRole('columnheader',{name:/feature_00/}).waitFor();
    await mkdir(output,{recursive:true});
    await page.screenshot({path:`${output}/dataset-desktop.png`});
    await page.setViewportSize({width:390,height:844});
    await page.screenshot({path:`${output}/dataset-mobile.png`});
    await page.setViewportSize({width:1280,height:720});
    await page.evaluate(path => {window.location.hash=path;}, `/artifacts/${uid}/${encodeURIComponent(node.id)}/model`);
    await page.getByRole('button',{name:'Visualization',exact:true}).click();
    await page.getByRole('region',{name:'Model preview'}).waitFor();
    await page.getByText('xgboost',{exact:true}).waitFor();
    await page.getByRole('table',{name:'Recorded hyperparameters'}).waitFor();
    await page.screenshot({path:`${output}/model-desktop.png`});
    await page.setViewportSize({width:390,height:844});
    await page.screenshot({path:`${output}/model-mobile.png`});
    assert.ok(requests.some(path=>path.endsWith('/dataset-preview')));
    assert.ok(requests.some(path=>path.endsWith('/model-preview')));
    assert.ok(!requests.some(path=>path.includes('/argo/artifacts/') && /\/(dataset|model)$/.test(path)), 'Preview must not download artifact payloads.');
    assert.deepEqual(errors,[]);
    console.log(`Preview screenshots: ${output}`);
  } finally { await browser.close(); }
});


test('stock ROC and confusion-matrix viewers consume native classification metadata', {timeout:120000, skip:!process.env.ARGO_CLASSIFICATION_RUN_ID}, async () => {
  const id=process.env.ARGO_CLASSIFICATION_RUN_ID;
  const response=await fetch(`${origin}/argo/api/v1/archived-workflows/${id}?namespace=${namespace}`,{headers:{Authorization:`Bearer ${token}`}});
  assert.ok(response.ok);
  const run=await response.json();
  const node=Object.values(run.status.nodes).find(node=>node.outputs?.artifacts?.some(artifact=>artifact.name==='metrics'));
  assert.ok(node);
  const browser=await chromium.launch({channel:process.env.PLAYWRIGHT_CHANNEL || 'chrome'});
  try {
    const page=await browser.newPage({viewport:{width:1280,height:900}});
    const errors=[];
    page.on('pageerror',error=>errors.push(error.message));
    await page.goto(`${origin}/argo.html?namespace=${namespace}#/artifacts/${id}/${encodeURIComponent(node.id)}/metrics`);
    await page.getByLabel('Kubernetes bearer token').fill(token);
    await page.getByRole('button',{name:'Connect',exact:true}).click();
    await page.getByRole('dialog').waitFor({state:'hidden'});
    await page.getByRole('button',{name:'Visualization',exact:true}).click();
    await page.getByText('ROC Curve',{exact:true}).waitFor();
    await page.getByText('Confusion Matrix: metrics',{exact:true}).waitFor();
    await page.waitForFunction(() => {
      const curve=document.querySelector('.recharts-line-curve');
      if (!curve || !(curve.getAttribute('d')?.length>10)) return false;
      const dash=getComputedStyle(curve).strokeDasharray;
      return dash==='none' || parseFloat(dash)>=curve.getTotalLength()-1;
    });
    await mkdir(output,{recursive:true});
    await page.screenshot({path:`${output}/classification-desktop.png`,fullPage:true});
    assert.deepEqual(errors,[]);
  } finally {await browser.close();}
});
