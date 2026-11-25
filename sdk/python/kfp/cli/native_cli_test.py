# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0

import sys
import types
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from kfp.cli import visualization
from kfp.cli.compile_ import collect_pipeline_or_component_func, compile_
from kfp.dsl.pipeline_context import Pipeline

ROOT = Path(__file__).resolve().parents[4]


@pytest.mark.parametrize('function_name', [None, 'step'])
def test_cli_loads_exact_file_without_module_name_collisions(
    tmp_path, monkeypatch, function_name
):
    cached = types.ModuleType('components')
    monkeypatch.setitem(sys.modules, 'components', cached)
    before = list(sys.path)
    for directory, image in [('one', 'image-one'), ('two', 'image-two')]:
        path = tmp_path / directory / 'components.py'
        path.parent.mkdir()
        path.write_text(
            'from kfp import dsl\n@dsl.container_component\ndef step():\n    return dsl.ContainerSpec(image='
            + repr(image)
            + ', command=["true"])\n'
        )
        loaded = collect_pipeline_or_component_func(str(path), function_name)
        assert loaded.component_spec.implementation.container.image == image
    path.write_text(path.read_text().replace('image-two', 'image-new'))
    assert (
        collect_pipeline_or_component_func(
            str(path), function_name
        ).component_spec.implementation.container.image
        == 'image-new'
    )
    assert sys.modules['components'] is cached
    assert sys.path == before


def test_cli_native_resource_options(tmp_path):
    path = tmp_path / 'cron.yaml'
    before = Pipeline.get_execution_caching_default()
    result = CliRunner().invoke(
        compile_,
        [
            '--py',
            str(ROOT / 'samples/argo-native/components.py'),
            '--output',
            str(path),
            '--resource-kind',
            'CronWorkflow',
            '--schedule',
            '0 9 * * *',
            '--namespace',
            'test',
            '--disable-caching',
        ],
    )
    assert result.exit_code == 0, result.output
    manifest = yaml.safe_load(path.read_text())
    assert manifest['kind'] == 'CronWorkflow'
    assert manifest['metadata']['namespace'] == 'test'
    assert manifest['spec']['schedules'] == ['0 9 * * *']
    assert Pipeline.get_execution_caching_default() == before


def test_python_preview_is_native_and_does_not_require_image_digests():
    spec = visualization.load_spec(ROOT / 'samples/argo-native/components.py')
    assert spec['kind'] == 'WorkflowTemplate'
    assert 'root' not in spec
    view = visualization.build_view(spec)
    assert [node['label'] for node in view['graphs'][0]['nodes']] == [
        'prepare',
        'train',
        'evaluate',
    ]
    assert 'prepare' in visualization.render_markdown(view)


def test_native_preview_rejects_recursive_templates():
    spec = {
        'kind': 'Workflow',
        'metadata': {'name': 'bad'},
        'spec': {
            'entrypoint': 'root',
            'templates': [
                {
                    'name': 'root',
                    'dag': {'tasks': [{'name': 'loop', 'template': 'root'}]},
                }
            ],
        },
    }
    with pytest.raises(ValueError, match='recursive'):
        visualization.validate_spec(spec)
