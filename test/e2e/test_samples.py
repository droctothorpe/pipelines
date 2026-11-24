# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Every pipeline definition under samples/ compiled and executed unchanged.

Two definitions fail stock compilation and are expected failures.
Samples that need hardware or credentials skip unless
KFP_TEST_PREREQUISITES=1. Set KFP_TEST_DISABLE_CACHING=1 for a cold pass
and KFP_TEST_SERVICE_ACCOUNT for the PVC sample.

Every run must reach the sample's expected state; samples that stock's
per-sample runner tests also checked (branches taken, loop items and
outputs, cache hits, retries, exit handlers, OOM failures) carry those
assertions in ``e2e.samples.EXPECTATIONS``, read from the Argo workflow.
"""

import os
from uuid import uuid4

import pytest

from e2e import support
from e2e.samples import (
    FLAKY,
    Outcome,
    cases,
    compile_case,
    frozen_baseline,
    verify_previews,
)

BASELINE = frozen_baseline()


def _params():
    for case in cases():
        marks = [pytest.mark.full]
        key = case.source + ':' + case.pipeline
        if case.function is None:
            marks.append(
                pytest.mark.xfail(
                    reason='Stock baseline compile failure: '
                    + str(case.load_error),
                    strict=BASELINE.get(key) == 'failed',
                    run=False,
                )
            )
        if case.prerequisite:
            marks.append(pytest.mark.prerequisite)
        yield pytest.param(case, id=case.id, marks=marks)


@pytest.mark.parametrize('case', list(_params()))
def test_sample_runs_unchanged(client, settings, namespace, record, case):
    if case.prerequisite and not os.environ.get('KFP_TEST_PREREQUISITES'):
        pytest.skip(case.prerequisite)
    package = compile_case(case, settings.output)
    cold = bool(os.environ.get('KFP_TEST_DISABLE_CACHING'))

    def submit(arguments):
        submitted = client.create_run_from_pipeline_package(
            str(package),
            arguments=arguments,
            run_name='Stock sample ' + case.pipeline + ' ' + uuid4().hex[:8],
            experiment_name='Stock sample compatibility',
            namespace=namespace,
            service_account=os.environ.get('KFP_TEST_SERVICE_ACCOUNT') or None,
            enable_caching=False if cold else None,
        )
        done = submitted.wait_for_run_completion(timeout=case.timeout)
        return submitted, done, support.workflow(client, done)

    submitted, done, raw = submit(case.parameters)
    attempts = 1
    if done.state != case.expected_state and case.key in FLAKY:
        # Stock ran these samples as written, randomness included.
        submitted, done, raw = submit(case.parameters)
        attempts = 2
    nodes = (raw.get('status') or {}).get('nodes', {})
    assert done.state == case.expected_state, support.phases(raw)
    entry = {
        'run_id': submitted.run_id,
        'state': done.state,
        'caching': 'disabled' if cold else 'default',
        'attempts': attempts,
    }

    def rerun(arguments=None):
        """The stock assertions' second submission of the same package."""
        merged = {**case.parameters, **(arguments or {})}
        again, completed, workflow = submit(merged)
        entry.setdefault('reruns', []).append(
            {
                'run_id': again.run_id,
                'state': completed.state,
                'arguments': merged,
            }
        )
        return Outcome(client, completed, workflow, cold, rerun)

    if case.expected_state == 'FAILED':
        cleanup = [
            n
            for n in nodes.values()
            if n.get('type') == 'Pod' and n.get('displayName') == 'exit'
        ]
        assert cleanup and all(
            n.get('phase') == 'Succeeded' for n in cleanup
        ), 'Expected failing body with a successful exit handler'
    if '/artifact_previews/' in case.source:
        entry['verified_previews'] = verify_previews(
            client,
            done,
            namespace,
            raw['metadata']['name'],
            nodes,
            disabled='disabled' in case.pipeline,
        )
    if case.expect:
        details = case.expect(Outcome(client, done, raw, cold, rerun))
        entry.update(details or {})
    record(sample=case.id, **entry)
