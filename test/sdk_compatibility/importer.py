# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Verify native import metadata, payload staging and reimport/cache behavior.

Set KFP_TEST_TOKEN and KFP_IMPORT_URI to an existing text Dataset containing 37.
"""

import json
import os
import time
from uuid import uuid4

import kfp
from kfp import dsl


@dsl.component
def check(data: dsl.Input[dsl.Dataset], expected: int) -> int:
    from pathlib import Path

    assert int(Path(data.path).read_text()) == expected
    assert data.metadata['rows'] == expected
    assert data.metadata['description'] == 'Imported from ' + data.uri
    return expected


@dsl.pipeline(name='native-importer-user-program')
def pipeline(uri: str, rows: int = 37):
    imported = dsl.importer(
        artifact_uri=uri,
        artifact_class=dsl.Dataset,
        metadata={'rows': rows, 'description': f'Imported from {uri}'},
    )
    check(data=imported.output, expected=rows)


@dsl.pipeline(name='native-reimport-user-program')
def reimport_pipeline(uri: str, rows: int = 37):
    imported = dsl.importer(
        artifact_uri=uri,
        artifact_class=dsl.Dataset,
        reimport=True,
        metadata={'rows': rows, 'description': f'Imported from {uri}'},
    )
    check(data=imported.output, expected=rows)


if __name__ == '__main__':
    namespace = os.environ.get('KFP_TEST_NAMESPACE', 'kfp-argo')
    client = kfp.Client(
        host=os.environ.get('KFP_TEST_HOST', 'http://127.0.0.1:3003'),
        namespace=namespace,
        existing_token=os.environ['KFP_TEST_TOKEN'],
    )
    report = []
    for function, reuse in [(pipeline, True), (reimport_pipeline, False)]:
        for iteration in range(2):
            run = client.create_run_from_pipeline_func(
                function,
                arguments={'uri': os.environ['KFP_IMPORT_URI']},
                run_name='Importer compatibility ' + uuid4().hex[:8],
                experiment_name='SDK backwards compatibility',
                namespace=namespace,
            )
            for _ in range(100):
                complete = client.get_run(run.run_id)
                raw = client._run_api.transport.request(
                    'GET',
                    f'/argo/api/v1/workflows/{namespace}/{complete.pipeline_spec["metadata"]["name"]}',
                )
                errors = [
                    node.get('message')
                    for node in raw.get('status', {}).get('nodes', {}).values()
                    if node.get('displayName') == 'importer'
                    and node.get('phase') == 'Error'
                ]
                if errors:
                    client.terminate_run(run.run_id)
                    raise AssertionError(errors)
                if complete.state in ('SUCCEEDED', 'FAILED', 'CANCELED'):
                    break
                time.sleep(3)
            assert complete.state == 'SUCCEEDED', complete.to_dict()
            importer = next(
                node
                for node in raw['status']['nodes'].values()
                if node.get('displayName') == 'importer'
            )
            assert importer['type'] == 'DAG'
            if iteration:
                assert (
                    bool(importer.get('memoizationStatus', {}).get('hit'))
                    is reuse
                )
            consumer = next(
                node
                for node in raw['status']['nodes'].values()
                if node.get('displayName') == 'check'
            )
            if iteration:
                assert (
                    bool(consumer.get('memoizationStatus', {}).get('hit'))
                    is reuse
                )
            report.append(
                {'run_id': run.run_id, 'reuse': reuse, 'iteration': iteration}
            )
    print(json.dumps(report, indent=2))
