# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Recurring-run lifecycle through the public client; the owned schedule is
left disabled."""

import datetime
import time
from uuid import uuid4

import pytest
from kfp import compiler, dsl


@dsl.container_component
def step():
    return dsl.ContainerSpec(
        image='busybox:1.36', command=['sh', '-c', 'echo recurring; sleep 3']
    )


@dsl.pipeline(name='sdk-recurring-check')
def pipeline():
    step().set_caching_options(False)


@pytest.mark.full
def test_schedule_enables_disables_and_creates_runs(
    client, namespace, record, tmp_path
):
    package = str(tmp_path / 'pipeline.yaml')
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
        while time.monotonic() < deadline and not found:
            found = [
                run
                for run in client.list_runs(page_size=100).runs
                if run.recurring_run_id == schedule.recurring_run_id
            ]
            if not found:
                time.sleep(2)
        assert found, 'No recurring-run workflows observed'
        record(
            schedule_id=schedule.recurring_run_id,
            run_ids=[run.run_id for run in found],
        )
    finally:
        client.disable_recurring_run(schedule.recurring_run_id)
