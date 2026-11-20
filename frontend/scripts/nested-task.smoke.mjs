// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { test } from 'node:test';
import { chromium } from 'playwright';

test('nested task deep links expand ancestors and explain pod-free importers', {timeout:90000}, async()=>{
  const fixture=JSON.parse(await readFile(process.env.KFP_NESTED_UI_FIXTURE || '/tmp/kfp-nested-importer-ui-fixture.json','utf8'));
  const origin=process.env.ARGO_UI_URL || 'http://127.0.0.1:3014';
  const token=process.env.ARGO_READER_TOKEN;
  assert.ok(token);
  const response=await fetch(`${origin}/argo/api/v1/archived-workflows/${fixture.run_id}?namespace=${fixture.namespace}`,{headers:{Authorization:`Bearer ${token}`}});
  assert.ok(response.ok);
  const run=await response.json();
  const node=Object.values(run.status.nodes).find(n=>n.displayName==='importer');
  assert.ok(node && node.boundaryID!==run.metadata.name);
  const browser=await chromium.launch({channel:process.env.PLAYWRIGHT_CHANNEL || 'chrome'});
  try {
    const page=await browser.newPage({viewport:{width:1280,height:900}});
    const errors=[],paths=[];
    page.on('pageerror',error=>errors.push(error.message));
    page.on('request',request=>paths.push(new URL(request.url()).pathname));
    await page.goto(`${origin}/argo.html?namespace=${fixture.namespace}#/runs/details/${fixture.run_id}?task=${encodeURIComponent(node.id)}`);
    await page.getByLabel('Kubernetes bearer token').fill(token);
    await page.getByRole('button',{name:'Connect',exact:true}).click();
    await page.getByRole('dialog').waitFor({state:'hidden'});
    await page.getByRole('button',{name:'Task Details',exact:true}).click();
    await page.getByText('Importer',{exact:true}).waitFor();
    assert.ok((await page.locator('.react-flow__node').evaluateAll(nodes=>nodes.map(n=>n.getAttribute('data-id') || ''))).some(id=>id.includes(node.id)));
    await page.getByRole('button',{name:'Logs',exact:true}).click();
    await page.getByText('This importer resolves an artifact reference without an execution pod.',{exact:true}).waitFor();
    assert.ok(!paths.some(path=>path.endsWith('/main-logs') || path.endsWith('/log')));
    await page.screenshot({path:'/tmp/kfp-nested-importer-ui.png',fullPage:true,animations:'disabled'});
    assert.deepEqual(errors,[]);
  } finally {await browser.close();}
});
