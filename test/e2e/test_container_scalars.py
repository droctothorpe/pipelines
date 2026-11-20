# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Raw container outputs: typed values, caching, and producer-side validation
errors that stop the consumer."""

import pytest

from e2e import support
from e2e.pipelines.container_scalars import pipeline


@pytest.mark.smoke
def test_typed_outputs_validate_and_cache(client, record):
    for index in range(2):
        submitted, done = support.run_pipeline(
            client, pipeline, {'bad': ''}, timeout=300
        )
        raw = support.workflow(client, done)
        assert done.state == 'SUCCEEDED', support.phases(raw)
        assert (
            support.node_output(support.node(raw, 'check'))
            == 'typed outputs verified'
        )
        if index:
            source = support.node(raw, 'produce')
            assert source.get('memoizationStatus', {}).get('hit') is True, (
                source
            )
            assert not any(
                n.get('displayName') == 'execute' for n in support.nodes(raw)
            )
        record(run_id=submitted.run_id, iteration=index, state=done.state)


@pytest.mark.full
@pytest.mark.parametrize('bad', ['integer', 'boolean', 'items'])
def test_invalid_output_fails_the_producer_not_the_consumer(
    client, record, bad
):
    submitted, done = support.run_pipeline(
        client, pipeline, {'bad': bad}, timeout=300
    )
    raw = support.workflow(client, done)
    assert done.state == 'FAILED', support.phases(raw)
    assert support.node(raw, 'produce')['phase'] == 'Error'
    validation = support.node(raw, 'validate')
    assert validation['phase'] == 'Error', validation
    assert bad in validation.get('message', '').lower(), validation
    assert not any(
        n.get('displayName') == 'check' and n['type'] == 'Pod'
        for n in support.nodes(raw)
    )
    record(run_id=submitted.run_id, bad=bad, state=done.state)
