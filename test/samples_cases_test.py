# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""The sample corpus case table stays honest offline: baseline compile failures
are expected failures, prerequisites are named, recorded inputs apply."""

import json

from e2e.corpus import ROOT
from e2e.samples import cases, frozen_baseline


def test_case_table_matches_the_frozen_stock_baseline():
    table = {case.source + ':' + case.pipeline: case for case in cases()}
    baseline = frozen_baseline()
    assert set(table) == set(baseline)
    for key, status in baseline.items():
        assert (table[key].function is None) == (status == 'failed'), key
    assert len(table) == len(
        json.loads((ROOT / 'test/data/stock_samples.json').read_text())[
            'samples'
        ]
    )


def test_recorded_inputs_prerequisites_and_expectations():
    table = {case.source + ':' + case.pipeline: case for case in cases()}
    caching = table['samples/core/caching/caching_sample.py:caching_pipeline']
    assert caching.parameters == {'seconds': 1}
    exit_handler = table[
        'samples/core/exit_handler/exit_handler.py:pipeline_exit_handler'
    ]
    assert exit_handler.expected_state == 'FAILED'
    pvc = table['samples/core/kubernetes_pvc/kubernetes_pvc.py:my_pipeline']
    assert 'KFP_TEST_SERVICE_ACCOUNT' in pvc.prerequisite
    formats = table[
        'samples/core/artifact_previews/artifact_previews.py:artifact_preview_formats_pipeline'
    ]
    assert formats.timeout == 1500 and 'minutes' in formats.prerequisite
    plain = table['samples/core/retry/retry.py:retry_sample_pipeline']
    assert (
        plain.prerequisite is None
        and plain.parameters == {}
        and plain.timeout == 600
    )
