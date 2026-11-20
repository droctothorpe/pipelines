# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Compare native compilation with the frozen stock sample corpus."""

import json

import pytest
from e2e.corpus import ROOT, definitions, sources
from kfp import compiler

FIXTURE = json.loads((ROOT / 'test/data/stock_samples.json').read_text())
SOURCES = {str(path.relative_to(ROOT)): source for path, source in sources()}


@pytest.mark.parametrize(
    'sample',
    [
        pytest.param(
            row,
            id=row['source'] + ':' + row['pipeline'],
            marks=(
                pytest.mark.xfail(
                    reason='Pre-existing stock sample error: ' + row['error'],
                    strict=False,
                )
                if row['compile'] == 'failed'
                else []
            ),
        )
        for row in FIXTURE['samples']
    ],
)
def test_stock_sample_dsl_compiles(sample, tmp_path):
    path = ROOT / sample['source']
    namespace, _, error = definitions(path, SOURCES[sample['source']])
    assert sample['pipeline'] in namespace, error
    target = tmp_path / 'pipeline.yaml'
    compiler.Compiler().compile(namespace[sample['pipeline']], str(target))
    assert target.is_file()
