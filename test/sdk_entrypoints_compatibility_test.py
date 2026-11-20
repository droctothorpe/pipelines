# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Public non-IR entrypoints must survive the native backend migration."""

import importlib

import kfp
import pytest
from click.testing import CliRunner
from kfp.cli.cli import cli


@pytest.mark.parametrize(
    'command',
    [
        'experiment',
        'experiments',
        'pipeline',
        'pipelines',
        'run',
        'runs',
        'recurring-run',
        'recurring-runs',
        'diagnose-me',
        'component',
        'components',
        'dsl',
        'visualize',
    ],
)
def test_stock_cli_groups(command, monkeypatch):
    # Stock CLI initializes Client before dispatching a subcommand, even for help.
    monkeypatch.setattr(kfp.client, 'Client', lambda *args, **kwargs: None)
    result = CliRunner().invoke(cli, [command, '--help'], obj={})
    assert result.exit_code == 0, result.output


@pytest.mark.parametrize(
    'module,symbol',
    [
        ('compiler', 'Compiler'),
        ('components', 'load_component_from_text'),
        ('dsl', 'pipeline'),
    ],
)
def test_deprecated_v2_aliases_use_current_implementations(module, symbol):
    alias = importlib.import_module(f'kfp.v2.{module}')
    current = importlib.import_module(f'kfp.{module}')
    assert getattr(alias, symbol) is getattr(current, symbol)


def test_registry_client_is_importable():
    from kfp.registry import RegistryClient

    assert callable(RegistryClient.upload_pipeline)
    assert callable(RegistryClient.download_pipeline)
