from pathlib import Path
import datetime
import json
import subprocess
import time
import requests
from kfp import Client

ROOT=Path(__file__).parent
API='http://127.0.0.1:8888'
client=Client(host=API, namespace='kubeflow')
experiment=client.create_experiment('PR14478 E2E September 25', namespace='kubeflow')
ids_path=ROOT/'evidence/ids.json'
ids=json.loads(ids_path.read_text()) if ids_path.exists() else {'experiment':experiment.experiment_id,'pipelines':{},'versions':{},'runs':{}}
def save(): (ROOT/'evidence/ids.json').write_text(json.dumps(ids,indent=2)+'\n')
for kind, filename in [('main','validation-pipeline.yaml'),('retry','retry-pipeline.yaml'),('live','live-pipeline.yaml')]:
    if kind in ids['pipelines']: continue
    pipeline=client.upload_pipeline(str(ROOT/filename), pipeline_name='PR14478 E2E 20260925 '+kind, namespace='kubeflow')
    ids['pipelines'][kind]=pipeline.pipeline_id
    versions=client.list_pipeline_versions(pipeline.pipeline_id)
    ids['versions'][kind]=versions.pipeline_versions[0].pipeline_version_id
for kind, pipeline, params in [('baseline','main',{'score':0.93}),('comparison','main',{'score':0.97}),('retry','retry',{}),('live','live',{})]:
    if kind in ids['runs'] and kind != 'live': continue
    run=client.run_pipeline(experiment.experiment_id,'PR14478 E2E '+kind,pipeline_id=ids['pipelines'][pipeline],version_id=ids['versions'][pipeline],params=params)
    ids['runs'][kind]=run.run_id
    save()
    print(kind,run.run_id,flush=True)

# Observe a real, still-running pod through the direct v2 HTTP route.
for attempt in range(90):
    result=subprocess.run(['kubectl','--context','orbstack','-n','kubeflow','get','pods','-l','pipeline/runid='+ids['runs']['live'],'-o','json'],check=True,capture_output=True,text=True)
    pods=json.loads(result.stdout)['items']
    candidates=[p for p in pods if p['metadata']['labels'].get('pipelines.kubeflow.org/pod-role')=='container-executor' and p['status']['phase']=='Running' and any(c['name']=='main' for c in p['spec']['containers'])]
    if candidates:
        pod=candidates[0]['metadata']['name']; break
    time.sleep(2)
else: raise AssertionError('Live-log pod did not start')
start=time.monotonic()
url=f"{API}/apis/v2beta1/runs/{ids['runs']['live']}/nodes/{pod}/log?follow=true"
lines=[]
with requests.get(url,stream=True,timeout=(10,12)) as response:
    response.raise_for_status()
    for line in response.iter_lines(chunk_size=1,decode_unicode=True):
        lines.append(line)
        if 'LIVE_STREAM_FIRST_LINE' in line: break
    else: raise AssertionError('Missing first live line')
elapsed=time.monotonic()-start
run=requests.get(f"{API}/apis/v2beta1/runs/{ids['runs']['live']}",timeout=10).json()
assert run['state'] not in ('SUCCEEDED','FAILED','CANCELED'), run
(ROOT/'evidence/live-stream.json').write_text(json.dumps({'url':url,'first_line_elapsed_seconds':elapsed,'run_state_when_received':run['state'],'pod':pod,'lines':lines,'client_closed_after_first_line':True},indent=2)+'\n')
print('LIVE STREAM RECEIVED BEFORE RUN ENDED',elapsed,run['state'],flush=True)

for attempt in range(100):
    states={}
    for kind, run_id in ids['runs'].items():
        response=requests.get(f'{API}/apis/v2beta1/runs/{run_id}',timeout=15); response.raise_for_status()
        data=response.json(); states[kind]=data['state']
        (ROOT/f'evidence/run-{kind}.json').write_text(json.dumps(data,indent=2)+'\n')
    print(states,flush=True)
    if all(s in ('SUCCEEDED','FAILED','CANCELED') for s in states.values()): break
    time.sleep(3)
else: raise AssertionError('Runs did not reach terminal states')
assert states=={'baseline':'SUCCEEDED','comparison':'SUCCEEDED','retry':'FAILED','live':'SUCCEEDED'}, states
for kind,run_id in ids['runs'].items():
    response=requests.get(f'{API}/apis/v2beta1/runs/{run_id}/tasks',timeout=15); response.raise_for_status()
    (ROOT/f'evidence/tasks-{kind}.json').write_text(json.dumps(response.json(),indent=2)+'\n')

# The removed upload format must fail without creating a pipeline.
response=requests.post(API+'/apis/v2beta1/pipelines/upload',params={'name':'PR14478 rejected Argo','namespace':'kubeflow'},files={'uploadfile':('legacy.yaml','apiVersion: argoproj.io/v1alpha1\nkind: Workflow\nmetadata:\n  generateName: old-\nspec:\n  entrypoint: main\n  templates:\n  - name: main\n    container:\n      image: alpine\n      command: [echo, hello]\n')},timeout=20)
assert response.status_code==400,(response.status_code,response.text)
(ROOT/'evidence/raw-argo-rejection.json').write_text(json.dumps({'status':response.status_code,'body':response.json()},indent=2)+'\n')
print('INITIAL VALIDATION PASSED',flush=True)
