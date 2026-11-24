# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Compare native compilation with the frozen stock sample corpus.

Each stock sample that compiles is also pinned to a golden Argo manifest under
``test/data/golden`` (stock pinned its IR the same way). Regenerate with
``KFP_UPDATE_GOLDENS=1`` after an intended compiler change and review the diff.
"""

import difflib
import json
import os

import pytest
from e2e.corpus import ROOT, definitions, sources
from kfp import compiler

FIXTURE = json.loads((ROOT / 'test/data/stock_samples.json').read_text())
SOURCES = {str(path.relative_to(ROOT)): source for path, source in sources()}
GOLDEN = ROOT / 'test/data/golden'


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
    golden = GOLDEN / (
        path.stem + '__' + sample['pipeline'].replace('_', '-') + '.yaml'
    )
    if os.environ.get('KFP_UPDATE_GOLDENS'):
        golden.parent.mkdir(exist_ok=True)
        golden.write_text(target.read_text())
    assert golden.is_file(), (
        f'Missing golden {golden}; run with KFP_UPDATE_GOLDENS=1.'
    )
    expected, actual = golden.read_text(), target.read_text()
    assert actual == expected, (
        'Compiled manifest differs from the golden:\n'
        + ''.join(
            difflib.unified_diff(
                expected.splitlines(keepends=True),
                actual.splitlines(keepends=True),
                str(golden.relative_to(ROOT)),
                'compiled',
            )
        )
    )
