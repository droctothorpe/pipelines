# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""User-level authoring programs must not need native compiler workarounds."""

import yaml
from kfp import compiler, dsl, kubernetes


@dsl.component
def stock_echo(value: str) -> str:
    return value


def compile_pipeline(tmp_path, pipeline, **options):
    path = tmp_path / 'pipeline.yaml'
    compiler.Compiler(**options).compile(pipeline, str(path))
    return yaml.safe_load(path.read_text())


def containers(manifest):
    return [
        template
        for template in manifest['spec']['templates']
        if 'container' in template
    ]


def test_ordinary_decorators_compile_with_caching_on_by_default(tmp_path):
    @dsl.pipeline(name='stock-defaults')
    def pipeline(value: str = 'hello'):
        stock_echo(value=value)

    manifest = compile_pipeline(tmp_path, pipeline)
    assert manifest['kind'] == 'WorkflowTemplate'
    task = containers(manifest)[0]
    assert 'memoize' in task
    assert 'toJson(inputs.parameters)' in task['memoize']['key']
    assert task['memoize']['maxAge'] == '', (
        'Stock caching has no arbitrary one-hour expiry'
    )


def test_native_manifest_embeds_runtime_instead_of_requiring_fork_in_image(
    tmp_path,
):
    @dsl.pipeline(name='portable-runtime')
    def pipeline():
        stock_echo(value='hello')

    task = containers(compile_pipeline(tmp_path, pipeline))[0]
    command = task['container']['command']
    assert not any(
        'python3 -m kfp.dsl.executor_main' in item for item in command
    )
    assert any('base64' in item and 'zlib' in item for item in command)
    assert '--argo_input' in task['container']['args']


def test_cache_settings_remain_user_controlled(tmp_path):
    @dsl.pipeline(name='stock-cache-settings')
    def pipeline():
        stock_echo(value='cached')
        stock_echo(value='uncached').set_caching_options(False)

    assert [
        'memoize' in task
        for task in containers(compile_pipeline(tmp_path, pipeline))
    ] == [True, False]
    assert all(
        'memoize' not in task
        for task in containers(
            compile_pipeline(tmp_path, pipeline, disable_caching=True)
        )
    )


def test_secrets_and_config_maps_do_not_force_caching_off(tmp_path):
    @dsl.pipeline(name='stock-external-config')
    def pipeline():
        task = stock_echo(value='hello')
        kubernetes.use_secret_as_env(task, 'credentials', {'key': 'API_KEY'})
        kubernetes.use_config_map_as_env(task, 'settings', {'key': 'SETTING'})

    task = containers(compile_pipeline(tmp_path, pipeline))[0]
    assert 'memoize' in task
    assert any(
        'secretKeyRef' in item.get('valueFrom', {})
        for item in task['container']['env']
    )
    assert any(
        'configMapKeyRef' in item.get('valueFrom', {})
        for item in task['container']['env']
    )


def test_equivalent_component_calls_share_cache_identity(tmp_path):
    @dsl.pipeline(name='same-component')
    def pipeline():
        stock_echo(value='same')
        stock_echo(value='same')

    tasks = containers(compile_pipeline(tmp_path, pipeline))
    assert tasks[0]['name'] != tasks[1]['name']
    assert tasks[0]['memoize']['key'] == tasks[1]['memoize']['key']


def test_automatic_cache_keys_are_scoped_to_pipeline_identity(tmp_path):
    @dsl.pipeline(name='first-pipeline')
    def first():
        stock_echo(value='same')

    @dsl.pipeline(name='second-pipeline')
    def second():
        stock_echo(value='same')

    assert (
        containers(compile_pipeline(tmp_path, first))[0]['memoize']['key']
        != containers(compile_pipeline(tmp_path, second))[0]['memoize']['key']
    )


def test_custom_cache_key_overrides_automatic_values(tmp_path):
    @dsl.pipeline(name='custom-cache-key')
    def pipeline():
        stock_echo(value='first').set_caching_options(
            True, cache_key='user-version'
        )
        stock_echo(value='second').set_caching_options(
            True, cache_key='user-version'
        )
        stock_echo(value='third').set_caching_options(
            True, cache_key='another-version'
        )

    tasks = containers(compile_pipeline(tmp_path, pipeline))
    assert tasks[0]['memoize']['key'] == tasks[1]['memoize']['key']
    assert tasks[0]['memoize']['key'] != tasks[2]['memoize']['key']
    assert 'inputs.parameters' not in tasks[0]['memoize']['key']


def test_oneof_artifact_merge_keeps_uri_and_metadata_companions(tmp_path):
    from sdk_compatibility.oneof import pipeline

    manifest = compile_pipeline(tmp_path, pipeline)
    merged = [
        template
        for template in manifest['spec']['templates']
        if any(
            'fromExpression' in artifact
            for artifact in template.get('outputs', {}).get('artifacts', [])
        )
    ]
    assert len(merged) == 1
    artifacts = merged[0]['outputs']['artifacts']
    assert len(artifacts) == 2
    assert any(artifact.get('optional') for artifact in artifacts)
    names = [
        parameter['name'] for parameter in merged[0]['outputs']['parameters']
    ]
    assert any(name.startswith('kfp-uri-') for name in names)
    assert any(name.startswith('kfp-meta-') for name in names)


def test_importer_uses_native_artifact_references_without_a_driver_pod(
    tmp_path,
):
    @dsl.container_component
    def read(data: dsl.Input[dsl.Dataset]):
        return dsl.ContainerSpec(
            image='busybox:1.36', command=['cat', data.path]
        )

    @dsl.pipeline(name='importer-compatibility')
    def pipeline(uri: str = 'https://example.com/data'):
        imported = dsl.importer(
            artifact_uri=uri,
            artifact_class=dsl.Dataset,
            metadata={'source': uri, 'rows': 2},
        )
        read(data=imported.output)

    manifest = compile_pipeline(tmp_path, pipeline)
    importers = [
        template
        for template in manifest['spec']['templates']
        if any(
            artifact['name'] == 'artifact'
            for artifact in template.get('outputs', {}).get('artifacts', [])
        )
    ]
    assert len(importers) == 1
    assert 'container' not in importers[0]
    assert importers[0]['memoize']['maxAge'] == ''
    assert 'fromExpression' in importers[0]['outputs']['artifacts'][0]


def test_pipeline_task_positional_arguments_do_not_shift_cache_default():
    # execute_locally=False occupied the third position in the stock constructor.
    task = dsl.PipelineTask(
        stock_echo.component_spec, {'value': 'hello'}, False
    )
    assert task._task_spec.enable_caching is True
