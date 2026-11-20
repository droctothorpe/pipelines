// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { chromium } from 'playwright';

// Read-only acceptance against the deliberately invalid raw-container regression run.
test('native validation stays inside the user component while errors and pod logs remain visible', {timeout:90000}, async()=>{
  const origin=process.env.ARGO_UI_URL || 'http://127.0.0.1:3014';
  const namespace=process.env.ARGO_NAMESPACE || 'kfp-argo';
  const token=process.env.ARGO_READER_TOKEN;
  const uid=process.env.ARGO_VALIDATION_RUN_ID;
  assert.ok(token && uid, 'Set ARGO_READER_TOKEN and ARGO_VALIDATION_RUN_ID');
  const response=await fetch(`${origin}/argo/api/v1/archived-workflows/${uid}?namespace=${namespace}`,{headers:{Authorization:`Bearer ${token}`}});
  assert.ok(response.ok);
  const run=await response.json();
  const node=Object.values(run.status.nodes).find(node=>node.displayName==='produce');
  assert.equal(node.phase,'Error');
  const browser=await chromium.launch({channel:process.env.PLAYWRIGHT_CHANNEL || 'chrome'});
  try {
    const page=await browser.newPage({viewport:{width:1280,height:900}});
    const errors=[],requests=[];
    page.on('pageerror',error=>errors.push(error.message));
    page.on('request',request=>requests.push(new URL(request.url()).pathname));
    await page.goto(`${origin}/argo.html?namespace=${namespace}#/runs/details/${uid}?task=${encodeURIComponent(node.id)}`);
    await page.getByLabel('Kubernetes bearer token').fill(token);
    await page.getByRole('button',{name:'Connect',exact:true}).click();
    await page.getByRole('dialog').waitFor({state:'hidden'});
    await page.getByRole('alert').filter({hasText:'invalid operation'}).waitFor();
    assert.equal(await page.locator('.react-flow__node-SUB_DAG').count(),0);
    await page.screenshot({path:'/tmp/kfp-native-validation-error-desktop.png',fullPage:true,animations:'disabled'});
    await page.getByRole('button',{name:'Task Details',exact:true}).click();
    await page.getByText('Container',{exact:true}).waitFor();
    const logResponse=page.waitForResponse(response=>response.url().endsWith('/main-logs'));
    await page.getByRole('button',{name:'Logs',exact:true}).click();
    assert.equal((await logResponse).status(),200);
    await page.getByRole('progressbar',{name:'Loading logs'}).waitFor({state:'hidden'});
    assert.ok(!(await page.locator('body').innerText()).includes('task pod is not available'));
    assert.ok(requests.some(path=>path.includes('/main-logs')));
    assert.ok(!requests.some(path=>path.includes(`/${node.id}/main-logs`)), 'Logs must use the actual execution pod');
    await page.screenshot({path:'/tmp/kfp-native-validation-ui.png',fullPage:true});
    await page.setViewportSize({width:390,height:844});
    await page.screenshot({path:'/tmp/kfp-native-validation-mobile.png',fullPage:true});
    assert.deepEqual(errors,[]);
  } finally {await browser.close();}
});
