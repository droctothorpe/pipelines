# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""The portable bridge prepared by this SDK executes under unmodified PyPI
KFP."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from e2e import stock_runtime

STOCK = '2.17.0'


@pytest.mark.no_cluster
@pytest.mark.full
def test_bridge_runs_under_stock_kfp(tmp_path):
    if shutil.which('uv') is None:
        pytest.skip('uv is required to create the stock KFP environment')
    stock_runtime.prepare(tmp_path)
    result = subprocess.run(
        [
            'uv',
            'run',
            '--no-project',
            '--python',
            '3.11',
            '--with',
            'kfp==' + STOCK,
            'python',
            '-I',
            str(Path(stock_runtime.__file__).resolve()),
            'run',
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'Passed with unmodified KFP ' + STOCK in result.stdout, result.stdout
    assert sys.version_info >= (3, 11)
