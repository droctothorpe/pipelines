# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Experiment archival cascades to runs and schedules without terminating runs,
and restoring the experiment leaves children archived."""

import datetime
from uuid import uuid4

import kfp
import pytest

from e2e import support
from e2e.pipelines.default_pipeline import pipeline


@pytest.mark.full
def test_archive_cascade_and_restore(client, record, tmp_path):
    suffix = uuid4().hex[:10]
    value = int(suffix, 16)
    experiment = client.create_experiment('Archive lifecycle ' + suffix)
    package = tmp_path / 'pipeline.yaml'
    kfp.compiler.Compiler().compile(pipeline, str(package))
    schedule = None
    try:
        start = datetime.datetime.now(
            datetime.timezone.utc
        ) + datetime.timedelta(days=1)
        schedule = client.create_recurring_run(
            experiment_id=experiment.experiment_id,
            job_name='Archive lifecycle ' + suffix,
            pipeline_package_path=str(package),
            params={'value': value},
            interval_second=60,
            enabled=False,
            start_time=start.isoformat(),
            end_time=(start + datetime.timedelta(minutes=10)).isoformat(),
        )
        client.enable_recurring_run(schedule.recurring_run_id)
        assert (
            client.get_recurring_run(schedule.recurring_run_id).status
            == 'ENABLED'
        )
        run = client.create_run_from_pipeline_package(
            str(package),
            arguments={'value': value},
            run_name='Archive lifecycle ' + suffix,
            experiment_name=experiment.display_name,
            namespace=client.get_user_namespace(),
        )
        before = client.get_run(run.run_id)
        original = before.pipeline_spec['metadata']
        client.archive_experiment(experiment.experiment_id)
        assert (
            client.get_experiment(
                experiment_id=experiment.experiment_id
            ).storage_state
            == 'ARCHIVED'
        )
        assert client.get_run(run.run_id).storage_state == 'ARCHIVED'
        assert (
            client.get_recurring_run(schedule.recurring_run_id).status
            == 'DISABLED'
        )
        with pytest.raises(kfp.server_api.ApiException) as denied:
            client.unarchive_run(run.run_id)
        assert denied.value.status == 400 and 'experiment first' in str(
            denied.value
        )
        completed = run.wait_for_run_completion(timeout=600)
        assert completed.state == 'SUCCEEDED', support.failures(completed)
        raw = support.workflow(client, completed)
        assert raw['metadata']['uid'] == original['uid']
        assert 'shutdown' not in raw['spec']
        producer = support.node(raw, 'prepare')
        metadata = client._run_api.transport.request(
            'GET',
            f'/argo/artifacts/{original["namespace"]}/{original["name"]}/{producer["id"]}/kfp-metadata',
        )
        artifact = next(
            item for item in metadata['artifacts'] if item['port'] == 'dataset'
        )
        assert artifact['metadata']['value'] == value
        assert artifact['producer']['run'] == original['uid']
        client.unarchive_experiment(experiment.experiment_id)
        assert client.get_run(run.run_id).storage_state == 'ARCHIVED'
        assert (
            client.get_recurring_run(schedule.recurring_run_id).status
            == 'DISABLED'
        )
        client.unarchive_run(run.run_id)
        assert client.get_run(run.run_id).storage_state == 'AVAILABLE'
        record(
            experiment_id=experiment.experiment_id,
            run_id=run.run_id,
            schedule_id=schedule.recurring_run_id,
            state_before_archive=before.state,
            final_state=completed.state,
        )
    finally:
        if schedule is not None:
            client.disable_recurring_run(schedule.recurring_run_id)
