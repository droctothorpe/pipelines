# Copyright 2026 The Kubeflow Authors
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0

import importlib.util
import json
from pathlib import Path

import pytest
import yaml

from kfp.dsl import argo_runtime

ROOT = Path(__file__).resolve().parents[4]


@pytest.mark.parametrize('single,count', [(False, 0), (False, 2), (True, 1)])
def test_bridge_consumes_staged_artifact_lists(
    tmp_path, monkeypatch, single, count
):
    from typing import List

    from kfp import dsl
    from kfp.dsl.argo_staging_test import identity

    def consume(values: dsl.Input[List[dsl.Dataset]]) -> int:
        if single:
            assert isinstance(values, dsl.Dataset)
            values = [values]
        assert isinstance(values, list)
        for value in values:
            assert value.uri.startswith('s3://data/original-run/')
            assert value.metadata['value'] == 7
        return sum(int(Path(value.path).read_text()) for value in values)

    if single:
        consume.__annotations__['values'] = dsl.Input[dsl.Dataset]
    records = []
    for index in range(count):
        path = tmp_path / str(index)
        path.write_text(str(index + 1))
        records.append({'identity': identity(), 'path': str(path)})
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(
        json.dumps(
            {'schema': argo_runtime.SCHEMA, 'inputs': {'values': records}}
        )
    )
    for key in ('KFP_ARGO_RUN_UID', 'KFP_ARGO_NODE_ID', 'KFP_ARGO_NAMESPACE'):
        monkeypatch.setenv(key, 'consumer')
    output = tmp_path / 'result'
    summary = argo_runtime.execute(
        consume,
        {
            'schema': argo_runtime.SCHEMA,
            'outputDirectory': str(tmp_path),
            'inputs': {
                'values': {
                    'type': 'system.Dataset@0.0.1',
                    'stagedArtifact' if single else 'artifactList': True,
                    'manifestPath': str(manifest),
                }
            },
            'outputs': {'Output': {'type': 'Integer', 'path': str(output)}},
        },
        [],
    )
    assert output.read_text() == str(sum(range(1, count + 1)))
    assert len(summary['inputs']) == count
    assert all(
        item['producer']['run'] == 'original-run' for item in summary['inputs']
    )


@pytest.mark.parametrize(
    'kind,value',
    [
        ('String', 'null'),
        ('String', ''),
        ('Integer', 0),
        ('Float', 0.5),
        ('Boolean', False),
        ('List', [None, 'null']),
        ('Dict', {'value': None}),
    ],
)
def test_nullable_parameters_keep_none_distinct_from_values(kind, value):
    wire = 'Nullable' + kind
    assert (
        argo_runtime.deserialize(argo_runtime.serialize(None, wire), wire)
        is None
    )
    assert (
        argo_runtime.deserialize(argo_runtime.serialize(value, wire), wire)
        == value
    )
    assert argo_runtime.serialize(value, wire) != 'null'


def test_bridge_fills_new_task_config_fields_on_older_executor_objects():
    import inspect
    from types import SimpleNamespace

    def component(config):
        return config.resource_claims

    claims = [{'name': 'device', 'resourceClaimTemplateName': 'device'}]
    wrapped = argo_runtime._with_task_configs(
        component, {'config': {'resourceClaims': claims}}
    )
    assert inspect.signature(wrapped) == inspect.signature(component)
    assert (
        inspect.getfullargspec(wrapped).args
        == inspect.getfullargspec(component).args
    )
    assert wrapped(config=SimpleNamespace(resources={})) == claims


def test_bridge_supports_existing_executor_constructor(tmp_path, monkeypatch):
    class ExistingExecutor(argo_runtime._StagedExecutor):
        def __init__(self, executor_input, function_to_execute):
            super().__init__(
                executor_input, function_to_execute, artifact_previews=False
            )

    monkeypatch.setattr(argo_runtime, '_StagedExecutor', ExistingExecutor)
    for key, value in [
        ('KFP_ARGO_RUN_UID', 'run'),
        ('KFP_ARGO_NODE_ID', 'task'),
        ('KFP_ARGO_NAMESPACE', 'ns'),
    ]:
        monkeypatch.setenv(key, value)

    def echo(value: int) -> int:
        return value

    output = tmp_path / 'result'
    argo_runtime.execute(
        echo,
        {
            'schema': argo_runtime.SCHEMA,
            'outputDirectory': str(tmp_path),
            'inputs': {'value': {'type': 'Integer'}},
            'outputs': {'Output': {'type': 'Integer', 'path': str(output)}},
        },
        [{'name': 'value', 'value': '7'}],
    )
    assert output.read_text() == '7'


@pytest.mark.parametrize(
    'present,value,expected',
    [(False, '', 'none'), (True, '', ''), (True, 'null', 'null')],
)
def test_failure_optional_input_distinguishes_none_from_strings(
    tmp_path, monkeypatch, present, value, expected
):
    for key in ('KFP_ARGO_RUN_UID', 'KFP_ARGO_NODE_ID', 'KFP_ARGO_NAMESPACE'):
        monkeypatch.setenv(key, 'test')

    def echo(value: str = None) -> str:
        return 'none' if value is None else value

    path = tmp_path / 'result'
    argo_runtime.execute(
        echo,
        {
            'schema': argo_runtime.SCHEMA,
            'outputDirectory': str(tmp_path),
            'inputs': {
                'value': {
                    'type': 'String',
                    'optional': True,
                    'presenceParameter': 'kfp-present-value',
                }
            },
            'outputs': {'Output': {'type': 'String', 'path': str(path)}},
        },
        [
            {'name': 'value', 'value': value},
            {'name': 'kfp-present-value', 'value': json.dumps(present)},
        ],
    )
    assert path.read_text() == expected


def test_classification_metrics_need_no_user_written_payload(
    tmp_path, monkeypatch
):
    from kfp import dsl

    def report(metrics: dsl.Output[dsl.ClassificationMetrics]):
        metrics.log_confusion_matrix(['negative', 'positive'], [[3, 1], [1, 5]])
        metrics.log_roc_curve([0.0, 0.1, 1.0], [0.0, 0.9, 1.0], [1.0, 0.5, 0.0])

    for key in ('KFP_ARGO_RUN_UID', 'KFP_ARGO_NODE_ID', 'KFP_ARGO_NAMESPACE'):
        monkeypatch.setenv(key, 'test')
    path = tmp_path / 'metrics'
    metadata = tmp_path / 'metrics-meta.json'
    summary = argo_runtime.execute(
        report,
        {
            'schema': argo_runtime.SCHEMA,
            'outputDirectory': str(tmp_path),
            'inputs': {},
            'outputs': {
                'metrics': {
                    'type': 'system.ClassificationMetrics@0.0.1',
                    'path': str(path),
                    'metadataPath': str(metadata),
                    'uri': 's3://bucket/{run}/{task}/metrics',
                }
            },
        },
        [],
    )
    assert json.loads(path.read_text())['confusionMatrix']['rows'][0][
        'row'
    ] == [3, 1]
    assert summary['metrics'] == {}, (
        'Classification structures are not scalar metrics'
    )


@pytest.mark.parametrize('enabled', [True, False])
def test_native_bridge_preserves_default_and_disabled_artifact_previews(
    tmp_path, monkeypatch, enabled
):
    from kfp import dsl

    def produce(dataset: dsl.Output[dsl.Dataset]):
        directory = Path(dataset.path)
        directory.mkdir()
        (directory / 'data.csv').write_text('name,value\\na,1\\nb,2\\n')

    for key in ('KFP_ARGO_RUN_UID', 'KFP_ARGO_NODE_ID', 'KFP_ARGO_NAMESPACE'):
        monkeypatch.setenv(key, 'test')
    path = tmp_path / 'dataset'
    metadata = tmp_path / 'dataset-meta.json'
    argo_runtime.execute(
        produce,
        {
            'schema': argo_runtime.SCHEMA,
            'artifactPreviews': enabled,
            'outputDirectory': str(tmp_path),
            'inputs': {},
            'outputs': {
                'dataset': {
                    'type': 'system.Dataset@0.0.1',
                    'path': str(path),
                    'metadataPath': str(metadata),
                    'uri': 's3://bucket/{run}/{task}/dataset',
                }
            },
        },
        [],
    )
    descriptor = json.loads(metadata.read_text())['metadata'].get(
        '_kfp_preview'
    )
    assert bool(descriptor) is enabled
    assert Path(str(path) + '.kfp-preview.json').exists() is enabled
    if enabled:
        assert descriptor == {'version': 2, 'storage': 'sibling'}


@pytest.mark.parametrize('code', [None, 0])
def test_successful_system_exit_still_writes_metadata(
    tmp_path, monkeypatch, code
):
    def finish():
        raise SystemExit(code)

    for key in ('KFP_ARGO_RUN_UID', 'KFP_ARGO_NODE_ID', 'KFP_ARGO_NAMESPACE'):
        monkeypatch.setenv(key, 'test')
    argo_runtime.execute(
        finish,
        {
            'schema': argo_runtime.SCHEMA,
            'outputDirectory': str(tmp_path),
            'inputs': {},
            'outputs': {},
        },
        [],
    )
    assert (
        json.loads((tmp_path / 'metadata.json').read_text())['producer']['run']
        == 'test'
    )


@pytest.mark.parametrize('value', [True, False])
def test_boolean_output_path_accepts_python_spelling(
    tmp_path, monkeypatch, value
):
    from kfp import dsl

    def produce(result: dsl.OutputPath(bool)):
        Path(result).write_text(str(value))

    for key in ('KFP_ARGO_RUN_UID', 'KFP_ARGO_NODE_ID', 'KFP_ARGO_NAMESPACE'):
        monkeypatch.setenv(key, 'test')
    path = tmp_path / 'result'
    argo_runtime.execute(
        produce,
        {
            'schema': argo_runtime.SCHEMA,
            'outputDirectory': str(tmp_path),
            'inputs': {},
            'outputs': {'result': {'type': 'Boolean', 'path': str(path)}},
        },
        [],
    )
    assert path.read_text() == json.dumps(value)


def test_large_metadata_is_not_inlined_into_workflow_parameters(
    tmp_path, monkeypatch
):
    from kfp import dsl

    def produce(dataset: dsl.Output[dsl.Dataset]):
        Path(dataset.path).write_text('payload')
        dataset.metadata['large'] = 'x' * 100_000

    for key, value in [
        ('KFP_ARGO_RUN_UID', 'run'),
        ('KFP_ARGO_NODE_ID', 'task'),
        ('KFP_ARGO_NAMESPACE', 'ns'),
    ]:
        monkeypatch.setenv(key, value)
    port = {
        'type': 'system.Dataset@0.0.1',
        'path': str(tmp_path / 'payload'),
        'metadataPath': str(tmp_path / 'dataset.json'),
        'identityPath': str(tmp_path / 'identity.json'),
        'uri': 's3://bucket/{run}/{task}/dataset',
    }
    argo_runtime.execute(
        produce,
        {
            'schema': argo_runtime.SCHEMA,
            'outputDirectory': str(tmp_path),
            'outputs': {'dataset': port},
        },
        [],
    )
    full = json.loads(Path(port['metadataPath']).read_text())
    identity = json.loads(Path(port['identityPath']).read_text())
    assert full['metadata']['large'] == 'x' * 100_000
    assert 'metadata' not in identity
    assert len(json.dumps(identity)) < 1000
    assert identity['producer'] == full['producer']

    def consume(dataset: dsl.Input[dsl.Dataset]):
        assert len(dataset.metadata['large']) == 100_000

    inputs = {
        'dataset': {key: port[key] for key in ('type', 'path', 'metadataPath')}
    }
    contract = {
        'schema': argo_runtime.SCHEMA,
        'outputDirectory': str(tmp_path / 'consumer'),
        'inputs': inputs,
    }
    parameters = [{'name': 'kfp-meta-dataset', 'value': json.dumps(identity)}]
    argo_runtime.execute(consume, contract, parameters)
    Path(port['metadataPath']).unlink()
    with pytest.raises(ValueError, match='metadata unavailable'):
        argo_runtime.execute(consume, contract, parameters)


@pytest.mark.parametrize(
    'kind,value',
    [
        ('String', '"{{workflow.uid}}"\n'),
        ('Boolean', False),
        ('Integer', 2),
        ('Float', 1.25),
        ('List', [1, 'two']),
        ('Dict', {'quote': '"'}),
    ],
)
def test_parameter_roundtrip(kind, value):
    assert (
        argo_runtime.deserialize(argo_runtime.serialize(value, kind), kind)
        == value
    )


@pytest.mark.parametrize(
    'kind,value',
    [('Boolean', '1'), ('Integer', 'true'), ('Float', 'NaN'), ('List', '{}')],
)
def test_bad_parameters(kind, value):
    with pytest.raises(ValueError):
        argo_runtime.deserialize(value, kind)


@pytest.mark.parametrize(
    'kind,value',
    [
        ('Integer', True),
        ('Float', '1.2'),
        ('Boolean', 1),
        ('List', {}),
        ('Unknown', 1),
    ],
)
def test_serialize_rejects_wrong_type(kind, value):
    with pytest.raises(ValueError):
        argo_runtime.serialize(value, kind)


@pytest.mark.parametrize('value', ['[NaN]', '{"value":Infinity}'])
def test_nested_nonfinite_parameters(value):
    with pytest.raises(ValueError):
        argo_runtime.deserialize(
            value, 'List' if value.startswith('[') else 'Dict'
        )


def test_handwritten_workflow_contract(tmp_path, monkeypatch):
    """Stage the exact handwritten ports as Argo does, without transferring
    data."""
    spec = importlib.util.spec_from_file_location(
        'demo', ROOT / 'samples/argo-native/components.py'
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    workflow = yaml.safe_load(
        (ROOT / 'samples/argo-native/handwritten.yaml').read_text()
    )
    artifacts = {}
    for template in workflow['spec']['templates'][1:]:
        name = template['name']
        monkeypatch.setenv('KFP_ARGO_RUN_UID', 'run-1')
        monkeypatch.setenv('KFP_ARGO_NODE_ID', name)
        monkeypatch.setenv('KFP_ARGO_NAMESPACE', 'demo')
        args = template['container']['args']
        contract = json.loads(
            args[args.index('--argo_input') + 1].replace(
                '/tmp/kfp', str(tmp_path / name)
            )
        )
        for port, declaration in contract.get('inputs', {}).items():
            if 'path' in declaration:
                Path(declaration['path']).parent.mkdir(
                    parents=True, exist_ok=True
                )
                Path(declaration['path']).write_bytes(artifacts[port][0])
                Path(declaration['metadataPath']).write_bytes(
                    artifacts[port][1]
                )
        summary = argo_runtime.execute(
            getattr(module, name),
            contract,
            [{'name': 'factor', 'value': '1.0'}],
        )
        for port, declaration in contract['outputs'].items():
            if 'metadataPath' in declaration:
                artifacts[port] = (
                    Path(declaration['path']).read_bytes(),
                    Path(declaration['metadataPath']).read_bytes(),
                )
                metadata = json.loads(artifacts[port][1])
                assert (
                    metadata['uri']
                    == f's3://argo-artifacts/run-1/{name}/{port}'
                )
        if name == 'train':
            assert summary['inputs'][0]['producer']['task'] == 'prepare'
            assert summary['artifacts'][0]['metadata']['dataset_uri'].endswith(
                '/prepare/dataset'
            )
        if name == 'evaluate':
            assert summary['metrics']['score'] == pytest.approx(2 / 3)
            assert float(
                Path(contract['outputs']['Output']['path']).read_text()
            ) == pytest.approx(2 / 3)


def test_bound_root_must_match_where_argo_stores_artifacts(tmp_path):
    """The run's URIs name the bucket it was bound to; Argo stages the
    repository it resolved for the pod.

    A mismatch fails before anything runs rather than recording URIs
    that point nowhere.
    """
    template = tmp_path / 'template'
    contract = {
        'outputs': {
            'data': {'uri': 's3://argo-artifacts/{run}/{task}/data'},
            'count': {'type': 'Integer'},
        }
    }
    argo_runtime.check_archive_location(contract, template)  # outside Argo
    template.write_text(
        json.dumps({'archiveLocation': {'s3': {'bucket': 'argo-artifacts'}}})
    )
    argo_runtime.check_archive_location(contract, template)
    assert argo_runtime.archive_root(template) == 's3://argo-artifacts'
    template.write_text(
        json.dumps({'archiveLocation': {'gcs': {'bucket': 'exports'}}})
    )
    assert argo_runtime.archive_root(template) == 'gs://exports'
    with pytest.raises(
        RuntimeError, match='bound to s3://argo-artifacts.*gs://exports'
    ):
        argo_runtime.check_archive_location(contract, template)
    template.write_text('{"archiveLocation": {"plugin": {"name": "x"}}}')
    argo_runtime.check_archive_location(contract, template)


def test_omitted_optional_artifact_input_is_none(tmp_path, monkeypatch):
    """L02: an optional artifact nobody supplied (empty URI and metadata
    defaults, no staged file) reaches the component as None."""
    from typing import Optional

    from kfp import dsl

    for key, value in [
        ('KFP_ARGO_RUN_UID', 'run'),
        ('KFP_ARGO_NODE_ID', 'task'),
        ('KFP_ARGO_NAMESPACE', 'ns'),
    ]:
        monkeypatch.setenv(key, value)
    seen = {}

    def describe(model: Optional[dsl.Input[dsl.Artifact]] = None) -> str:
        seen['model'] = model
        return 'absent' if model is None else model.uri

    contract = {
        'schema': argo_runtime.SCHEMA,
        'outputDirectory': str(tmp_path),
        'inputs': {
            'model': {
                'type': 'system.Artifact@0.0.1',
                'optional': True,
                'path': str(tmp_path / 'inputs' / 'model'),
                'metadataPath': str(tmp_path / 'inputs' / 'model.json'),
            }
        },
        'outputs': {
            'Output': {'type': 'String', 'path': str(tmp_path / 'Output')}
        },
    }
    argo_runtime.execute(
        describe,
        contract,
        [
            {'name': 'kfp-uri-model', 'value': ''},
            {'name': 'kfp-meta-model', 'value': ''},
        ],
    )
    assert seen == {'model': None}
    assert (tmp_path / 'Output').read_text() == 'absent'


def test_returned_artifact_without_uri_merges_into_the_assigned_one(
    tmp_path, monkeypatch
):
    """U50: a component may return its own ``dsl.Artifact``; on the KFP
    backend ``dsl.get_uri()`` yields '' for its URI, and stock's launcher
    then keeps the assigned location and merges the returned metadata."""
    from kfp import dsl

    for key in ('KFP_ARGO_RUN_UID', 'KFP_ARGO_NODE_ID', 'KFP_ARGO_NAMESPACE'):
        monkeypatch.setenv(key, 'test')
    path = tmp_path / 'Output'
    metadata_path = tmp_path / 'Output-meta.json'

    def make() -> dsl.Artifact:
        path.write_text('payload')
        return dsl.Artifact(uri='', metadata={'data': 123})

    summary = argo_runtime.execute(
        make,
        {
            'schema': argo_runtime.SCHEMA,
            'outputDirectory': str(tmp_path),
            'inputs': {},
            'outputs': {
                'Output': {
                    'type': 'system.Artifact@0.0.1',
                    'path': str(path),
                    'metadataPath': str(metadata_path),
                    'uri': 's3://bucket/{run}/{task}/Output',
                }
            },
        },
        [],
    )
    (recorded,) = summary['artifacts']
    assert recorded['uri'] == 's3://bucket/test/test/Output'
    assert recorded['metadata'] == {'data': 123}
    assert json.loads(metadata_path.read_text())['uri'] == recorded['uri']
