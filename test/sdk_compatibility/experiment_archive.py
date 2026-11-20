# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Verify experiment archival using only newly created, retained resources.

Reuses the default SDK pipeline without changing its graph. The owned schedule
starts tomorrow, has a bounded window, and is disabled in cleanup. Nothing is
deleted and no existing experiments/runs are modified.
"""

import argparse
import datetime
import json
import os
from pathlib import Path
from uuid import uuid4

import kfp
from default_pipeline import pipeline


def verify(client, output):
    output.mkdir(parents=True, exist_ok=True)
    suffix = uuid4().hex[:10]
    value = int(suffix, 16)
    experiment = client.create_experiment('Archive lifecycle ' + suffix)
    package = output / 'pipeline.yaml'
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
        # A lost creation response must not leave an enabled schedule behind.
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
        try:
            client.unarchive_run(run.run_id)
        except kfp.server_api.ApiException as error:
            assert error.status == 400 and 'experiment first' in str(error)
        else:
            raise AssertionError(
                'Restored a run while its experiment remained archived'
            )
        completed = run.wait_for_run_completion(timeout=600)
        assert completed.state == 'SUCCEEDED', completed.to_dict()
        workflow, live = client._run_api._workflow(run.run_id)
        assert live and workflow['metadata']['uid'] == original['uid']
        assert workflow['metadata']['name'] == original['name']
        assert 'shutdown' not in workflow['spec']
        producer = next(
            node
            for node in workflow['status']['nodes'].values()
            if node.get('type') == 'Pod'
            and node.get('displayName') == 'prepare'
        )
        root = f'/argo/artifacts/{original["namespace"]}/{original["name"]}/{producer["id"]}'
        metadata = client._run_api.transport.request(
            'GET', root + '/kfp-metadata'
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
        report = {
            'experiment_id': experiment.experiment_id,
            'run_id': run.run_id,
            'schedule_id': schedule.recurring_run_id,
            'state_before_archive': before.state,
            'final_state': completed.state,
            'artifact': artifact,
        }
        (output / 'execution.json').write_text(json.dumps(report, indent=2))
        return report
    finally:
        if schedule is not None:
            client.disable_recurring_run(schedule.recurring_run_id)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    token = os.environ.get('KFP_TEST_TOKEN', '')
    if not token:
        raise ValueError('KFP_TEST_TOKEN must be non-empty')
    client = kfp.Client(
        host=os.environ.get('KFP_TEST_HOST', 'http://127.0.0.1:3003'),
        namespace=os.environ.get('KFP_TEST_NAMESPACE', 'kfp-argo'),
        existing_token=token,
    )
    print(json.dumps(verify(client, args.output), indent=2))
