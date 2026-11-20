# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Read-only live verification of compact workflow inventories.

Requires an existing namespace with KFP-labelled workflows. No resources are
created, changed or deleted. Reports counts/response sizes, never parameter data
or credentials. Set KFP_TEST_TOKEN, KFP_TEST_HOST and KFP_TEST_NAMESPACE.
"""

import argparse
import json
import os
from pathlib import Path
from urllib.parse import quote

import kfp
import requests

FIELDS = ','.join(
    [
        'metadata',
        'items.metadata',
        'items.spec.shutdown',
        'items.spec.workflowTemplateRef',
        'items.status.phase',
        'items.status.startedAt',
        'items.status.finishedAt',
        'items.status.message',
    ]
)
METADATA = 'application/json;as=PartialObjectMetadataList;g=meta.k8s.io;v=v1,application/json;q=0.9'


def verify(host, namespace, token):
    if not token:
        raise ValueError('KFP_TEST_TOKEN must be non-empty')
    session = requests.Session()
    session.trust_env = False
    session.headers['Authorization'] = 'Bearer ' + token
    sizes = {}

    def pages(name, path, parameters, continuation, accept='application/json'):
        items, seen = [], set()
        sizes[name] = {'pages': 0, 'bytes': 0}
        while True:
            response = session.get(
                host.rstrip('/') + path,
                params=parameters,
                headers={'Accept': accept},
                timeout=30,
                allow_redirects=False,
            )
            if not response.ok:
                raise RuntimeError(
                    f'{name} request failed with HTTP {response.status_code}'
                )
            sizes[name]['pages'] += 1
            sizes[name]['bytes'] += len(response.content)
            value = response.json()
            items.extend(value.get('items') or [])
            cursor = value.get('metadata', {}).get('continue')
            if not cursor:
                return items
            if cursor in seen:
                raise AssertionError('Repeated inventory pagination token')
            seen.add(cursor)
            parameters[continuation] = cursor

    encoded = quote(namespace, safe='')
    index = pages(
        'metadata',
        f'/kubernetes/apis/argoproj.io/v1alpha1/namespaces/{encoded}/workflows',
        {'labelSelector': 'pipelines.kubeflow.org/pipeline', 'limit': 100},
        'continue',
        METADATA,
    )
    summaries = pages(
        'summaries',
        f'/argo/api/v1/workflows/{encoded}',
        {
            'listOptions.labelSelector': 'pipelines.kubeflow.org/pipeline',
            'listOptions.limit': 100,
            'listOptions.fieldSelector': 'ext.showRemainingItemCount=true',
            'fields': FIELDS,
        },
        'listOptions.continue',
    )
    assert index and summaries, (
        'Requires existing live workflows and Argo summary records'
    )
    assert all(
        not item.get('spec') and not item.get('status') for item in index
    ), 'Metadata projection was not honored'
    assert all(
        not item.get('spec', {}).get('templates')
        and not any(
            key in item.get('status', {})
            for key in ['nodes', 'compressedNodes', 'offloadNodeStatusVersion']
        )
        for item in summaries
    ), 'Summary projection was not honored'
    live = {item['metadata']['uid'] for item in index}
    assert all(
        item['metadata']['namespace'] == namespace for item in index + summaries
    )
    selected = index[0]['metadata']['uid']
    client = kfp.Client(host=host, namespace=namespace, existing_token=token)
    run = client.get_run(selected)
    assert run.run_id == selected and run.namespace == namespace
    assert run.pipeline_spec['spec'], 'Selected workflow was not hydrated'
    return {
        'namespace': namespace,
        'live_identities': len(live),
        'summary_rows': len(summaries),
        'unique_summary_identities': len(
            {item['metadata']['uid'] for item in summaries}
        ),
        'live_with_sql_summary': len(
            {
                item['metadata']['uid']
                for item in summaries
                if not item['metadata'].get('resourceVersion')
            }
            & live
        ),
        'selected_run_id': selected,
        'selected_state': run.state,
        'selected_task_count': run.task_count,
        'responses': sizes,
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = verify(
        os.environ.get('KFP_TEST_HOST', 'http://127.0.0.1:3003'),
        os.environ.get('KFP_TEST_NAMESPACE', 'kfp-argo'),
        os.environ.get('KFP_TEST_TOKEN', ''),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
