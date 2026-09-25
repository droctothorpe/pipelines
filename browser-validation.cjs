const { chromium } = require('../../../frontend/node_modules/playwright');
const fs = require('fs');
const path = require('path');
const assert = require('node:assert/strict');
const root = __dirname;
const idsPath = path.join(root, 'evidence/ids.json');
const ids = JSON.parse(fs.readFileSync(idsPath));
const base = 'http://127.0.0.1:8080/';
const observations = [];
(async () => {
 const browser = await chromium.launch({ channel: 'chrome', headless: true });
 const page = await browser.newPage({ viewport:{width:1440,height:1050} });
 page.on('pageerror', error => observations.push({type:'pageerror',message:error.message}));
 async function capture(name) {
  await page.screenshot({path:path.join(root,'screenshots',name+'.png'),fullPage:true});
  fs.writeFileSync(path.join(root,'evidence',name+'.txt'),await page.locator('body').innerText());
  observations.push({name,url:page.url()}); console.log('CAPTURED',name);
 }
 try {
  await page.goto(base+'#/runs/details/'+ids.runs.baseline,{waitUntil:'networkidle'});
  await page.getByText('echo',{exact:true}).waitFor();
  await page.getByText('report',{exact:true}).waitFor();
  await capture('01-native-v2-run-graph');
  await page.getByText('echo',{exact:true}).click();
  await page.getByText('Logs',{exact:true}).click();
  await page.getByText(/V2_COMPONENT_EXPORT_LOAD_OK/).first().waitFor();
  await capture('02-exported-component-logs');

  await page.goto(base+'#/compare?runlist='+ids.runs.baseline+','+ids.runs.comparison,{waitUntil:'networkidle'});
  await page.getByText('0.93',{exact:true}).first().waitFor();
  await page.getByText('0.97',{exact:true}).first().waitFor();
  await capture('03-native-metrics-comparison');
  await page.getByText('HTML',{exact:true}).click();
  await page.getByRole('combobox',{name:'First comparison artifact'}).click();
  await page.getByRole('option',{name:/PR14478 E2E baseline/}).click();
  await page.getByRole('combobox',{name:'Second comparison artifact'}).click();
  await page.getByRole('option',{name:/PR14478 E2E comparison/}).click();
  await page.frameLocator('iframe').first().getByText('Native v2 E2E validation',{exact:true}).waitFor();
  await page.frameLocator('iframe').nth(1).getByText('Native v2 E2E validation',{exact:true}).waitFor();
  await capture('04-html-artifacts');

  await page.goto(base+'#/runs/details/'+ids.runs.retry,{waitUntil:'networkidle'});
  await page.getByText('controlled-failure',{exact:true}).click();
  await page.getByText('Logs',{exact:true}).click();
  await page.getByText(/INTENTIONAL_FAILURE_FOR_RETRY/).first().waitFor();
  await capture('05-before-retry');
  const retryResponse = page.waitForResponse(r => r.request().method()==='POST' && r.url().includes(':retry'));
  await page.getByRole('button',{name:'Retry',exact:true}).click();
  await page.getByRole('dialog').getByRole('button',{name:'Retry',exact:true}).click();
  const response = await retryResponse;
  assert(response.ok(), await response.text());
  fs.writeFileSync(path.join(root,'evidence/retry-response.json'),JSON.stringify({status:response.status(),body:await response.json()},null,2));
  console.log('RETRY REQUESTED THROUGH UI');

  await page.goto(base+'#/runs/new?cloneFromRun='+ids.runs.baseline,{waitUntil:'networkidle'});
  await page.getByLabel('Run name',{exact:false}).fill('PR14478 E2E UI clone');
  if (await page.getByRole('button',{name:'Choose',exact:true}).count()) {
   await page.getByRole('button',{name:'Choose',exact:true}).click();
   await page.getByRole('dialog').getByText('PR14478 E2E September 25',{exact:true}).click();
   await page.getByRole('button',{name:'Use this experiment',exact:true}).click();
  }
  await capture('06-clone-form');
  const created = page.waitForResponse(r => r.request().method()==='POST' && r.url().endsWith('/apis/v2beta1/runs'));
  await page.getByRole('button',{name:'Start',exact:true}).click();
  const cloned = await created;
  assert(cloned.ok(),await cloned.text());
  ids.runs.clone=(await cloned.json()).run_id;
  fs.writeFileSync(idsPath,JSON.stringify(ids,null,2)+'\n');
  console.log('UI CLONE CREATED',ids.runs.clone);
 } catch (error) {
  await capture('browser-failure'); throw error;
 } finally {
  fs.writeFileSync(path.join(root,'evidence/browser-observations.json'),JSON.stringify(observations,null,2)+'\n');
  await browser.close();
 }
})().catch(error => { console.error(error); process.exit(1); });
