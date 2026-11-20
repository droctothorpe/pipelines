// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { chromium } from 'playwright';

test('Markdown artifacts retain stock formatting without scripts or tracking images', {timeout:90000}, async()=>{
  const origin=process.env.ARGO_UI_URL || 'http://127.0.0.1:3014';
  const namespace=process.env.ARGO_NAMESPACE || 'kfp-argo';
  const token=process.env.ARGO_READER_TOKEN;
  const uid=process.env.ARGO_MARKDOWN_RUN_ID;
  assert.ok(token && uid);
  const response=await fetch(`${origin}/argo/api/v1/archived-workflows/${uid}?namespace=${namespace}`,{headers:{Authorization:`Bearer ${token}`}});
  assert.ok(response.ok);
  const run=await response.json();
  const node=Object.values(run.status.nodes).find(n=>n.outputs?.artifacts?.some(a=>a.name==='document'));
  assert.ok(node);
  const browser=await chromium.launch({channel:process.env.PLAYWRIGHT_CHANNEL || 'chrome'});
  try {
    const page=await browser.newPage({viewport:{width:1280,height:900}});
    const errors=[],requests=[];
    page.on('pageerror',error=>errors.push(error.message));
    page.on('request',request=>requests.push(request.url()));
    await page.goto(`${origin}/argo.html?namespace=${namespace}#/artifacts/${uid}/${node.id}/document`);
    await page.getByLabel('Kubernetes bearer token').fill(token);
    await page.getByRole('button',{name:'Connect',exact:true}).click();
    await page.getByRole('dialog').waitFor({state:'hidden'});
    await page.getByRole('button',{name:'Visualization',exact:true}).click();
    await page.getByRole('heading',{name:'Evaluation report'}).waitFor();
    await page.getByRole('table').waitFor();
    assert.equal(await page.locator('.markdown-viewer strong').innerText(),'Passed');
    assert.equal(await page.locator('.markdown-viewer ul').evaluate(el=>getComputedStyle(el).listStyleType),'disc');
    assert.equal(await page.locator('.markdown-viewer script').count(),0);
    assert.equal(await page.evaluate(()=>window.__unexpectedMarkdownExecution),undefined);
    assert.ok(!requests.some(url=>url.includes('tracker.invalid')));
    await page.screenshot({path:'/tmp/kfp-markdown-desktop.png',fullPage:true,animations:'disabled'});
    await page.setViewportSize({width:390,height:844});
    await page.screenshot({path:'/tmp/kfp-markdown-mobile.png',fullPage:true,animations:'disabled'});
    assert.deepEqual(errors,[]);
  } finally {await browser.close();}
});
