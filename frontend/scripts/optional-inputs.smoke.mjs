// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { test } from 'node:test';
import { chromium } from 'playwright';

test('UI preserves None and literal null through SDK-compatible run parameters', {timeout:300000}, async()=>{
  const fixture=JSON.parse(await readFile(process.env.KFP_OPTIONAL_UI_FIXTURE || '/tmp/kfp-optional-ui-fixture.json','utf8'));
  const origin=process.env.ARGO_UI_URL || 'http://127.0.0.1:3014';
  const token=process.env.ARGO_EDITOR_TOKEN;
  assert.ok(token);
  const browser=await chromium.launch({channel:process.env.PLAYWRIGHT_CHANNEL || 'chrome'});
  try {
    const page=await browser.newPage({viewport:{width:1280,height:900}});
    const errors=[];
    page.on('pageerror',error=>errors.push(error.message));
    const url=`${origin}/argo.html?namespace=${fixture.namespace}#/runs/new?pipelineVersionId=${fixture.version_id}&experimentId=${fixture.experiment_id}`;
    await page.goto(url);
    await page.getByLabel('Kubernetes bearer token').fill(token);
    await page.getByRole('button',{name:'Connect',exact:true}).click();
    await page.getByRole('dialog').waitFor({state:'hidden'});
    const results=[];
    for (const value of [null,'null']) {
      if (results.length) await page.goto(url);
      await page.getByRole('checkbox',{name:'Use None for value'}).waitFor();
      assert.equal(await page.getByRole('checkbox',{name:'Use None for value'}).isChecked(),true);
      if (value!==null) {
        await page.getByRole('checkbox',{name:'Use None for value'}).uncheck();
        await page.getByLabel('value',{exact:true}).fill(value);
        await page.getByLabel('expected',{exact:true}).fill(JSON.stringify(value));
      }
      await page.getByLabel('Run name',{exact:false}).fill('UI optional '+Date.now());
      const submitted=page.waitForResponse(r=>r.request().method()==='POST' && new URL(r.url()).pathname===`/argo/api/v1/workflows/${fixture.namespace}`);
      await page.getByRole('button',{name:'Start',exact:true}).click();
      const response=await submitted;
      assert.ok(response.ok());
      const run=await response.json();
      assert.equal(JSON.parse(run.metadata.annotations['pipelines.kubeflow.org/parameters']).value,value);
      let complete;
      const deadline=Date.now()+180000;
      do {
        const response=await fetch(`${origin}/argo/api/v1/workflows/${fixture.namespace}/${run.metadata.name}`,{headers:{Authorization:`Bearer ${token}`}});
        assert.ok(response.ok); complete=await response.json();
        if (['Succeeded','Failed','Error'].includes(complete.status?.phase)) break;
        await new Promise(resolve=>setTimeout(resolve,2000));
      } while(Date.now()<deadline);
      assert.equal(complete.status.phase,'Succeeded',JSON.stringify(Object.values(complete.status.nodes || {}).filter(n=>['Failed','Error'].includes(n.phase)).map(n=>n.message)));
      results.push({run_id:run.metadata.uid,value});
    }
    assert.deepEqual(errors,[]);
    console.log(JSON.stringify(results));
  } finally {await browser.close();}
});
