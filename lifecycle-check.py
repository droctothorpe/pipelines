from pathlib import Path
import json
import time
import requests
from kfp import Client
ROOT=Path(__file__).parent
API='http://127.0.0.1:8888'
client=Client(host=API,namespace='kubeflow')
ids=json.loads((ROOT/'evidence/ids.json').read_text())
def save(): (ROOT/'evidence/ids.json').write_text(json.dumps(ids,indent=2)+'\n')
from types import SimpleNamespace
job=SimpleNamespace(recurring_run_id=ids['schedule']) if 'schedule' in ids else client.create_recurring_run(ids['experiment'],'PR14478 E2E pinned schedule',pipeline_id=ids['pipelines']['main'],version_id=ids['versions']['main'],interval_second=30,max_concurrency=1,no_catchup=True,params={'score':0.99})
ids['schedule']=job.recurring_run_id
save()
try:
    for _ in range(90):
        runs=client.list_runs(experiment_id=ids['experiment'],page_size=100).runs or []
        scheduled=[r for r in runs if r.recurring_run_id==job.recurring_run_id]
        if scheduled:
            ids['runs']['scheduled']=scheduled[0].run_id; save(); break
        time.sleep(2)
    else: raise AssertionError('Schedule produced no run')
finally:
    client.disable_recurring_run(job.recurring_run_id)
    data=requests.get(f"{API}/apis/v2beta1/recurringruns/{job.recurring_run_id}",timeout=15).json()
    (ROOT/'evidence/schedule-disabled.json').write_text(json.dumps(data,indent=2)+'\n')
    assert data['mode']=='DISABLE' and data['status']=='DISABLED',data

for _ in range(100):
    states={}
    for name,run_id in ids['runs'].items():
        r=requests.get(f'{API}/apis/v2beta1/runs/{run_id}',timeout=15); r.raise_for_status()
        data=r.json(); states[name]=data['state']
        (ROOT/f'evidence/run-{name}-final.json').write_text(json.dumps(data,indent=2)+'\n')
    print(states,flush=True)
    if all(s=='SUCCEEDED' for s in states.values()): break
    assert not any(s in ['FAILED','CANCELED'] for s in states.values()),states
    time.sleep(3)
else: raise AssertionError('Lifecycle runs did not complete')
for name,run_id in ids['runs'].items():
    r=requests.get(f'{API}/apis/v2beta1/runs/{run_id}/tasks',timeout=15); r.raise_for_status()
    data=r.json()
    (ROOT/f'evidence/tasks-{name}-final.json').write_text(json.dumps(data,indent=2)+'\n')
    if name=='clone':
        tasks=data.get('tasks',[])
        print('CLONE TASKS',[(t.get('display_name'),t.get('state')) for t in tasks],flush=True)
        assert sum(t['state']=='CACHED' for t in tasks)>=2,data

pipeline=ids['pipelines']['main']; version=ids['versions']['main']
response=requests.delete(f'{API}/apis/v2beta1/pipelines/{pipeline}/versions/{version}',timeout=20)
response.raise_for_status()
missing=requests.get(f'{API}/apis/v2beta1/pipelines/{pipeline}/versions/{version}',timeout=15)
assert missing.status_code==404,missing.text
full=requests.get(f"{API}/apis/v2beta1/runs/{ids['runs']['baseline']}",params={'view':'FULL'},timeout=15)
full.raise_for_status()
assert full.json()['pipeline_spec']['root']['dag']['tasks']
(ROOT/'evidence/deleted-version-and-full-view.json').write_text(json.dumps({'version_status':missing.status_code,'full_view_status':full.status_code,'full_view':full.json()},indent=2)+'\n')
print('LIFECYCLE PASSED: UI retry, UI clone/cache, scheduled execution, disabled schedule, persisted IR after version deletion',flush=True)
