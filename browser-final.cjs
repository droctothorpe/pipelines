const { chromium } = require('../../../frontend/node_modules/playwright');
const fs = require('fs');
const path = require('path');
const assert = require('node:assert/strict');
const root = __dirname;
const ids = JSON.parse(fs.readFileSync(path.join(root,'evidence/ids.json')));
(async () => {
 const browser=await chromium.launch({channel:'chrome',headless:true});
 const page=await browser.newPage({viewport:{width:1440,height:1050}});
 const network=[]; const errors=[];
 page.on('response',r=>{if(r.url().includes('/apis/'))network.push({url:r.url(),status:r.status()});});
 page.on('pageerror',e=>errors.push(e.message));
 async function capture(name) {
  await page.evaluate(()=>document.fonts.ready);
  await page.screenshot({path:path.join(root,'screenshots',name+'.png'),fullPage:true});
  fs.writeFileSync(path.join(root,'evidence',name+'.txt'),await page.locator('body').innerText());
  console.log('CAPTURED',name);
 }
 const base='http://127.0.0.1:8080/';
 try {
  await page.goto(base+'#/runs/details/'+ids.runs.baseline,{waitUntil:'networkidle'});
  await page.getByText('echo',{exact:true}).waitFor();
  await page.getByText('report',{exact:true}).waitFor();
  assert(network.some(r=>r.url.includes(ids.runs.baseline)&&r.url.includes('view=FULL')&&r.status===200),'Expected real FULL-view fallback');
  await capture('07-deleted-version-run-graph');
  await page.getByText('echo',{exact:true}).click();
  await page.getByText('Logs',{exact:true}).click();
  await page.getByText(/V2_COMPONENT_EXPORT_LOAD_OK/).first().waitFor();
  await capture('08-deleted-version-task-logs');
  await page.goto(base+'#/runs/details/'+ids.runs.retry,{waitUntil:'networkidle'});
  await page.getByText('controlled-failure',{exact:true}).click();
  await page.getByText('Logs',{exact:true}).click();
  await page.getByText(/RETRY_RECOVERED_SUCCESSFULLY/).first().waitFor();
  await capture('09-successful-retry-logs');
  await page.goto(base+'#/runs/details/'+ids.runs.clone,{waitUntil:'networkidle'});
  await page.getByText('echo',{exact:true}).waitFor();
  await capture('10-cached-ui-clone');
  await page.goto(base+'#/recurringrun/details/'+ids.schedule,{waitUntil:'networkidle'});
  await page.getByText('PR14478 E2E pinned schedule',{exact:true}).first().waitFor();
  await page.getByRole('button',{name:'Enable',exact:true}).waitFor();
  await capture('11-disabled-schedule');
  await page.goto(base+'#/runs/details/'+ids.runs.scheduled,{waitUntil:'networkidle'});
  await page.getByText('report',{exact:true}).waitFor();
  await capture('12-scheduled-run');
  await page.goto(base+'#/runs/details/'+ids.runs.live,{waitUntil:'networkidle'});
  await page.getByText('slow-log',{exact:true}).click();
  await page.getByText('Logs',{exact:true}).click();
  await page.getByText(/LIVE_STREAM_FINAL_LINE/).first().waitFor();
  await capture('13-live-run-final-logs');
  await page.goto(base+'#/experiments/details/'+ids.experiment,{waitUntil:'networkidle'});
  await page.getByText('PR14478 E2E baseline',{exact:true}).first().waitFor();
  await capture('14-validation-run-list');
  assert.equal(errors.length,0,JSON.stringify(errors));
  console.log('FINAL BROWSER VALIDATION PASSED');
 } catch(e) {await capture('browser-final-failure');throw e;}
 finally {
  fs.writeFileSync(path.join(root,'evidence/final-browser-network.json'),JSON.stringify({network,errors},null,2)+'\n');
  await browser.close();
 }
})().catch(e=>{console.error(e);process.exit(1)});
