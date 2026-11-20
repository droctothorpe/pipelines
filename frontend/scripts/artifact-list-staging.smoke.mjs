// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import assert from 'node:assert/strict';
import { readFile, writeFile } from 'node:fs/promises';
import { test } from 'node:test';
import { chromium } from 'playwright';

test('UI submits an immutable artifact-list version with init-only repository bindings', {timeout:240000}, async()=>{
  const fixture=JSON.parse(await readFile(process.env.KFP_LIST_UI_FIXTURE || '/tmp/kfp-artifact-list-ui-fixture.json','utf8'));
  const origin=process.env.ARGO_UI_URL || 'http://127.0.0.1:3014';
  const token=process.env.ARGO_EDITOR_TOKEN;
  assert.ok(token);
  const browser=await chromium.launch({channel:process.env.PLAYWRIGHT_CHANNEL || 'chrome'});
  try {
    const page=await browser.newPage({viewport:{width:1280,height:900}});
    const errors=[],paths=[];
    page.on('pageerror',error=>errors.push(error.message));
    page.on('request',request=>paths.push(new URL(request.url()).pathname));
    await page.goto(`${origin}/argo.html?namespace=${fixture.namespace}#/runs/new?pipelineVersionId=${fixture.version_id}&experimentId=${fixture.experiment_id}`);
    await page.getByLabel('Kubernetes bearer token').fill(token);
    await page.getByRole('button',{name:'Connect',exact:true}).click();
    await page.getByRole('dialog').waitFor({state:'hidden'});
    await page.getByLabel('Run name',{exact:false}).fill('UI artifact-list staging '+Date.now());
    await page.getByLabel(/^values/).fill('[3,4]');
    await page.getByLabel(/^nonce/).fill('UI-'+Date.now());
    await page.getByLabel(/^directory/).fill('false');
    const submission=page.waitForResponse(r=>r.request().method()==='POST' && new URL(r.url()).pathname===`/argo/api/v1/workflows/${fixture.namespace}`);
    await page.getByRole('button',{name:'Start',exact:true}).click();
    const response=await submission;
    assert.ok(response.ok());
    const run=await response.json();
    const template=run.spec.templates.find(t=>t.initContainers?.some(c=>c.name==='kfp-stage-artifacts'));
    const secretVolumes=template.volumes.filter(v=>v.secret).map(v=>v.name);
    assert.ok(secretVolumes.length);
    assert.ok(template.container.volumeMounts.every(v=>!secretVolumes.includes(v.name)));
    assert.ok(!paths.some(path=>path.includes('/secrets/')));
    let completed;
    const deadline=Date.now()+180000;
    do {
      const status=await fetch(`${origin}/argo/api/v1/workflows/${fixture.namespace}/${run.metadata.name}`,{headers:{Authorization:`Bearer ${token}`}});
      assert.ok(status.ok); completed=await status.json();
      if (['Succeeded','Failed','Error'].includes(completed.status?.phase)) break;
      await new Promise(resolve=>setTimeout(resolve,2000));
    } while(Date.now()<deadline);
    assert.equal(completed.status.phase,'Succeeded',JSON.stringify(Object.values(completed.status.nodes || {}).map(n=>({name:n.displayName,phase:n.phase,message:n.message}))));
    const consumer=Object.values(completed.status.nodes).find(n=>n.displayName==='consume');
    assert.equal(consumer.outputs.parameters.find(p=>p.name==='Output').value,'7');
    assert.deepEqual(errors,[]);
    const versions=await (await fetch(`${origin}/argo/api/v1/workflow-templates/${fixture.namespace}`,{headers:{Authorization:`Bearer ${token}`}})).json();
    const stored=versions.items.find(v=>v.metadata.uid===fixture.version_id);
    assert.ok(stored);
    const original=stored.spec.templates.find(t=>t.initContainers?.some(c=>c.name==='kfp-stage-artifacts'));
    assert.equal(original.initContainers.find(c=>c.name==='kfp-stage-artifacts').env.find(e=>e.name==='KFP_STAGING_REPOSITORY').value,'{}');
    await writeFile('/tmp/kfp-artifact-list-ui-result.json',JSON.stringify({run_id:run.metadata.uid,namespace:fixture.namespace,state:completed.status.phase}));
    console.log('Artifact-list UI run:',run.metadata.uid);
  } finally {await browser.close();}
});
