# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Keep live corpus verification explicit and safe when prerequisites fail."""

import importlib
import json
import runpy
import sys
from pathlib import Path
from types import SimpleNamespace

import kfp
import pytest
from sdk_compatibility import sample_corpus


@pytest.fixture
def runner(monkeypatch):
    monkeypatch.setitem(sys.modules, 'sample_corpus', sample_corpus)
    for name, value in [
        ('HOST', 'http://localhost:1'),
        ('NAMESPACE', 'test'),
        ('TOKEN', 'test-token'),
    ]:
        monkeypatch.setenv('KFP_TEST_' + name, value)
    return importlib.import_module('sdk_compatibility.run_samples')


def test_compile_failures_do_not_crash_execution_summary(
    runner, monkeypatch, tmp_path
):
    monkeypatch.setattr(
        sample_corpus, 'compile_samples', lambda _: [{'compile': 'failed'}]
    )
    monkeypatch.setattr(kfp, 'Client', lambda **_: None)
    monkeypatch.setattr(sys, 'argv', ['run_samples', '--output', str(tmp_path)])
    with pytest.raises(SystemExit) as result:
        runpy.run_path(runner.__file__, run_name='__main__')
    assert result.value.code is True


def test_empty_token_never_constructs_a_client(runner, monkeypatch, tmp_path):
    monkeypatch.setenv('KFP_TEST_TOKEN', '')
    monkeypatch.setattr(runner, 'compile_samples', lambda _: [])
    constructed = []
    monkeypatch.setattr(
        kfp, 'Client', lambda **kwargs: constructed.append(kwargs)
    )
    args = SimpleNamespace(
        output=tmp_path, include=None, timeout=10, service_account=None
    )
    with pytest.raises(ValueError, match='KFP_TEST_TOKEN'):
        runner.run(args)
    assert not constructed


@pytest.mark.parametrize('original_limit', [1, 7])
@pytest.mark.parametrize('cold', [False, True])
def test_bounded_execution_preserves_the_original_manifest_and_cache_choice(
    runner, monkeypatch, tmp_path, original_limit, cold
):
    original = tmp_path / 'pipeline.json'
    original.write_text(
        json.dumps(
            {
                'kind': 'WorkflowTemplate',
                'spec': {'parallelism': original_limit},
            }
        )
    )
    rows = [
        {
            'compile': 'passed',
            'source': 'example.py',
            'pipeline': 'example',
            'manifest': str(original),
        }
    ]
    monkeypatch.setattr(runner, 'compile_samples', lambda _: rows)
    calls = []
    done = SimpleNamespace(
        state='SUCCEEDED', pipeline_spec={'metadata': {'name': 'example'}}
    )

    def submit(path, **kwargs):
        calls.append((path, kwargs))
        return SimpleNamespace(
            run_id='run', wait_for_run_completion=lambda **_: done
        )

    transport = SimpleNamespace(
        request=lambda *args, **kwargs: {'status': {'nodes': {}}}
    )
    client = SimpleNamespace(
        create_run_from_pipeline_package=submit,
        _run_api=SimpleNamespace(transport=transport),
    )
    monkeypatch.setattr(kfp, 'Client', lambda **_: client)
    args = SimpleNamespace(
        output=tmp_path,
        include=None,
        timeout=10,
        service_account=None,
        parallelism=2,
        disable_caching=cold,
    )
    report = runner.run(args)
    assert (
        json.loads(original.read_text())['spec']['parallelism']
        == original_limit
    )
    assert json.loads(Path(calls[0][0]).read_text())['spec'][
        'parallelism'
    ] == min(original_limit, 2)
    assert calls[0][1]['enable_caching'] is (False if cold else None)
    assert report[0]['parallelism'] == min(original_limit, 2)
    assert report[0]['caching'] == (
        'disabled_explicitly' if cold else 'default'
    )
