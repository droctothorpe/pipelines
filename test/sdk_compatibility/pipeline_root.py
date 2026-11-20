# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Verify public pipeline_root overrides and actual Argo artifact locations.

Set KFP_TEST_TOKEN; optional KFP_TEST_HOST/NAMESPACE/CONTEXT/ARTIFACT_ROOT.
Only creates named test runs; does not delete resources or alter the deployment.
"""

import json
import os
import subprocess
from uuid import uuid4

import kfp
from default_pipeline import pipeline

if __name__ == '__main__':
    namespace = os.environ.get('KFP_TEST_NAMESPACE', 'kfp-argo')
    context = os.environ.get('KFP_TEST_CONTEXT', 'orbstack')
    client = kfp.Client(
        host=os.environ.get('KFP_TEST_HOST', 'http://127.0.0.1:3003'),
        namespace=namespace,
        existing_token=os.environ['KFP_TEST_TOKEN'],
    )
    base = os.environ.get(
        'KFP_TEST_ARTIFACT_ROOT', 's3://argo-artifacts'
    ).rstrip('/')
    report = []
    for suffix in ('normal', "quote' and space"):
        root = base + '/root-compat-' + uuid4().hex[:8] + '/' + suffix
        result = client.create_run_from_pipeline_func(
            pipeline,
            arguments={'value': 37},
            run_name='SDK pipeline root ' + uuid4().hex[:8],
            experiment_name='SDK backwards compatibility',
            namespace=namespace,
            pipeline_root=root,
            enable_caching=False,
        )
        completed = result.wait_for_run_completion(timeout=600)
        assert completed.state == 'SUCCEEDED', completed.to_dict()
        assert completed.runtime_config.pipeline_root == root
        workflows = json.loads(
            subprocess.check_output(
                [
                    'kubectl',
                    '--context',
                    context,
                    '-n',
                    namespace,
                    'get',
                    'workflows',
                    '-o',
                    'json',
                ]
            )
        )
        raw = next(
            item
            for item in workflows['items']
            if item['metadata']['uid'] == result.run_id
        )
        # Argo Server hydrates SQL-offloaded nodes; Kubernetes may retain only their reference.
        raw = client._run_api.transport.request(
            'GET',
            f'/argo/api/v1/workflows/{namespace}/{raw["metadata"]["name"]}',
        )
        uris = [
            parameter['value']
            for node in raw['status']['nodes'].values()
            for parameter in node.get('outputs', {}).get('parameters', [])
            if parameter['name'] == 'kfp-uri-dataset'
        ]
        assert uris and all(
            uri.startswith(root + '/' + result.run_id + '/') for uri in uris
        ), uris
        artifacts = [
            artifact
            for node in raw['status']['nodes'].values()
            for artifact in node.get('outputs', {}).get('artifacts', [])
            if artifact.get('name') == 'dataset'
        ]
        assert artifacts
        for artifact in artifacts:
            assert (
                's3://' + artifact['s3']['bucket'] + '/' + artifact['s3']['key']
                in uris
            )
        report.append(
            {'run_id': result.run_id, 'root': root, 'state': completed.state}
        )
    print(json.dumps(report, indent=2))
