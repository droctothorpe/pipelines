# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Verify native recurring-run SDK lifecycle; leave the owned schedule disabled.

Set KFP_TEST_TOKEN, and optionally KFP_TEST_HOST/KFP_TEST_NAMESPACE.
"""

import datetime
import json
import os
import tempfile
import time
from pathlib import Path
from uuid import uuid4

import kfp
from kfp import compiler, dsl


@dsl.container_component
def step():
    return dsl.ContainerSpec(
        image='busybox:1.36', command=['sh', '-c', 'echo recurring; sleep 3']
    )


@dsl.pipeline(name='sdk-recurring-check')
def pipeline():
    step().set_caching_options(False)


if __name__ == '__main__':
    namespace = os.environ.get('KFP_TEST_NAMESPACE', 'kfp-argo')
    client = kfp.Client(
        host=os.environ.get('KFP_TEST_HOST', 'http://127.0.0.1:3003'),
        namespace=namespace,
        existing_token=os.environ['KFP_TEST_TOKEN'],
    )
    with tempfile.TemporaryDirectory() as directory:
        package = str(Path(directory) / 'pipeline.yaml')
        compiler.Compiler().compile(pipeline, package)
        end = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
            minutes=2
        )
        schedule = client.create_recurring_run(
            job_name='SDK recurring check ' + uuid4().hex[:8],
            pipeline_package_path=package,
            interval_second=2,
            namespace=namespace,
            end_time=end.isoformat(),
            no_catchup=False,
        )
    try:
        assert schedule.status == 'ENABLED'
        client.disable_recurring_run(schedule.recurring_run_id)
        assert (
            client.get_recurring_run(schedule.recurring_run_id).status
            == 'DISABLED'
        )
        client.enable_recurring_run(schedule.recurring_run_id)
        deadline = time.monotonic() + 60
        found = []
        while time.monotonic() < deadline:
            found = [
                run
                for run in client.list_runs(page_size=100).runs
                if run.recurring_run_id == schedule.recurring_run_id
            ]
            if found:
                break
            time.sleep(2)
        assert found, 'No recurring-run workflows observed'
        print(
            json.dumps(
                {
                    'schedule_id': schedule.recurring_run_id,
                    'run_ids': [run.run_id for run in found],
                },
                indent=2,
            )
        )
    finally:
        client.disable_recurring_run(schedule.recurring_run_id)
