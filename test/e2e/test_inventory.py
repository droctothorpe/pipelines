# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Compact run inventories: the UI and SDK list metadata and summaries, not
whole workflows, and then hydrate one selected run."""

from urllib.parse import quote

import pytest
import requests

from e2e import support
from e2e.pipelines.default_pipeline import pipeline

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


def _pages(
    session, host, path, parameters, continuation, accept='application/json'
):
    items, seen, size = [], set(), {'pages': 0, 'bytes': 0}
    while True:
        response = session.get(
            host.rstrip('/') + path,
            params=parameters,
            headers={'Accept': accept},
            timeout=30,
            allow_redirects=False,
        )
        assert response.ok, f'{path} failed with HTTP {response.status_code}'
        size['pages'] += 1
        size['bytes'] += len(response.content)
        value = response.json()
        page = value.get('items') or []
        items.extend(page)
        cursor = value.get('metadata', {}).get('continue')
        if not cursor:
            return items, size
        if cursor in seen:
            # Argo Server's merged live/archived list can end on a repeated
            # offset with an empty page after deduplication, which the UI and
            # SDK treat as the end; a repeated token with items would loop.
            assert not page, 'Repeated inventory pagination token with items'
            return items, size
        seen.add(cursor)
        parameters[continuation] = cursor


@pytest.mark.smoke
def test_inventory_is_compact_and_hydrates_on_demand(client, settings, record):
    # The listing needs at least one labelled workflow in the namespace.
    seeded, done = support.run_pipeline(
        client, pipeline, {'value': 1}, timeout=300
    )
    assert done.state == 'SUCCEEDED', support.failures(done)
    session = requests.Session()
    session.trust_env = False
    session.headers['Authorization'] = 'Bearer ' + settings.token
    encoded = quote(settings.namespace, safe='')
    index, index_size = _pages(
        session,
        settings.host,
        f'/kubernetes/apis/argoproj.io/v1alpha1/namespaces/{encoded}/workflows',
        {'labelSelector': 'pipelines.kubeflow.org/pipeline', 'limit': 100},
        'continue',
        METADATA,
    )
    summaries, summary_size = _pages(
        session,
        settings.host,
        f'/argo/api/v1/workflows/{encoded}',
        {
            'listOptions.labelSelector': 'pipelines.kubeflow.org/pipeline',
            'listOptions.limit': 100,
            'listOptions.fieldSelector': 'ext.showRemainingItemCount=true',
            'fields': FIELDS,
        },
        'listOptions.continue',
    )
    assert index and summaries
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
    assert all(
        item['metadata']['namespace'] == settings.namespace
        for item in index + summaries
    )
    run = client.get_run(seeded.run_id)
    assert run.run_id == seeded.run_id and run.pipeline_spec['spec'], (
        'Selected workflow was not hydrated'
    )
    record(
        live_identities=len({item['metadata']['uid'] for item in index}),
        summary_rows=len(summaries),
        responses={'metadata': index_size, 'summaries': summary_size},
    )
