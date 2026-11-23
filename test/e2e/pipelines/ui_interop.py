# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""SDK-owned experiment, pipeline, version and run for the UI interop smoke.

The browser test invokes this module directly with a fixture path:
``python test/e2e/pipelines/ui_interop.py resources.json``.
"""

import json
import os
import sys
from pathlib import Path
from uuid import uuid4

from kfp import dsl

from e2e import support


@dsl.component
def echo(value: str) -> str:
    return value


@dsl.pipeline(name='sdk-ui-interop')
def pipeline(value: str = 'hello'):
    echo(value=value)


def create(client, namespace):
    suffix = uuid4().hex[:10]
    experiment = client.create_experiment('SDK UI experiment ' + suffix)
    uploaded = client.upload_pipeline_from_pipeline_func(
        pipeline, pipeline_name='SDK UI pipeline ' + suffix, namespace=namespace
    )
    version = client.list_pipeline_versions(
        uploaded.pipeline_id
    ).pipeline_versions[0]
    run = client.run_pipeline(
        experiment.experiment_id,
        'SDK UI run ' + suffix,
        pipeline_id=uploaded.pipeline_id,
        version_id=version.pipeline_version_id,
    )
    finished = client.wait_for_run_completion(run.run_id, timeout=600)
    assert finished.state == 'SUCCEEDED', finished.to_dict()
    return {
        'artifact_root': support.namespace_root(client, namespace),
        'namespace': namespace,
        'experiment_id': experiment.experiment_id,
        'experiment_name': experiment.display_name,
        'pipeline_id': uploaded.pipeline_id,
        'pipeline_name': uploaded.display_name,
        'version_id': version.pipeline_version_id,
        'run_id': run.run_id,
        'run_name': run.display_name,
    }


if __name__ == '__main__':
    import kfp

    namespace = os.environ.get('ARGO_NAMESPACE', 'kfp-argo')
    client = kfp.Client(
        host=os.environ.get('ARGO_UI_URL', 'http://127.0.0.1:3003'),
        namespace=namespace,
        existing_token=os.environ['ARGO_EDITOR_TOKEN'],
    )
    Path(sys.argv[1]).write_text(json.dumps(create(client, namespace)))
