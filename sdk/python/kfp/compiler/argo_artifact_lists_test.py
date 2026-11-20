# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0

import copy
import json
import re
from typing import List

import yaml

from kfp import compiler, dsl


@dsl.component
def produce(value: int, data: dsl.Output[dsl.Dataset]):
    from pathlib import Path

    Path(data.path).write_text(str(value))
    data.metadata['value'] = value


@dsl.component
def consume(values: dsl.Input[List[dsl.Dataset]]) -> int:
    from pathlib import Path

    return sum(int(Path(value.path).read_text()) for value in values)


@dsl.pipeline
def collected_pipeline(values: list):
    with dsl.ParallelFor(values) as value:
        item = produce(value=value)
    consume(values=dsl.Collected(item.outputs['data']))


def test_dynamic_artifact_list_uses_consumer_init_not_extra_pods(tmp_path):
    path = tmp_path / 'list.yaml'
    compiler.Compiler().compile(collected_pipeline, str(path))
    templates = yaml.safe_load(path.read_text())['spec']['templates']
    assert sum('container' in t for t in templates) == 2
    consumer = next(t for t in templates if t.get('initContainers'))
    assert len(consumer['initContainers']) == 1
    assert consumer['initContainers'][0]['name'] == 'kfp-stage-artifacts'
    assert [a['name'] for a in consumer['inputs']['artifacts']] == [
        'kfp-staging-inputs'
    ]
    assert (
        consumer['inputs']['artifacts'][0]['raw']['data']
        == '{{inputs.parameters}}'
    )
    assert any(
        p['name'] == 'kfp-meta-values' for p in consumer['inputs']['parameters']
    )
    assert consumer['memoize'], 'User caching remains enabled'
    for template in templates:
        if 'dag' in template:
            declared = {
                p['name']
                for p in template.get('inputs', {}).get('parameters', [])
            }
            references = set(
                re.findall(
                    r'\{\{inputs.parameters.([^}]+)\}\}',
                    json.dumps(template['dag']),
                )
            )
            assert references <= declared, (references, declared)


def test_large_collection_metadata_is_read_from_files_not_process_arguments(
    tmp_path,
):
    path = tmp_path / 'list.yaml'
    compiler.Compiler().compile(collected_pipeline, str(path))
    templates = yaml.safe_load(path.read_text())['spec']['templates']
    consumer = next(t for t in templates if t.get('initContainers'))
    assert '{{inputs.parameters}}' not in consumer['container']['args']
    assert '{{inputs.parameters}}' not in consumer['initContainers'][0]['args']


def test_collections_cross_nested_graph_and_condition_boundaries(tmp_path):
    @dsl.pipeline
    def forward(values: dsl.Input[List[dsl.Dataset]]) -> List[dsl.Dataset]:
        consume(values=values)
        return values

    @dsl.pipeline
    def nested(values: list, enabled: bool = True):
        with dsl.ParallelFor(values) as value:
            with dsl.ParallelFor([0, 1]):
                item = produce(value=value)
        with dsl.If(enabled == True):
            forwarded = forward(values=dsl.Collected(item.outputs['data']))
            consume(values=forwarded.output)

    path = tmp_path / 'nested.yaml'
    compiler.Compiler().compile(nested, str(path))
    spec = yaml.safe_load(path.read_text())['spec']
    graph = next(t for t in spec['templates'] if t['name'].endswith('-forward'))
    assert not graph['inputs'].get('artifacts')
    assert not graph['outputs'].get('artifacts')
    assert {p['name'] for p in graph['outputs']['parameters']} == {
        'kfp-uri-Output',
        'kfp-meta-Output',
    }


def test_artifact_list_iteration_stages_each_item_in_its_consumer_pod(tmp_path):
    @dsl.component
    def item(data: dsl.Input[dsl.Dataset]) -> str:
        return data.uri

    @dsl.pipeline
    def generate(values: list) -> List[dsl.Dataset]:
        with dsl.ParallelFor(values) as value:
            source = produce(value=value)
        return dsl.Collected(source.outputs['data'])

    @dsl.pipeline
    def pipeline(values: list):
        generated = generate(values=values)
        with dsl.ParallelFor(generated.output) as artifact:
            item(data=artifact)

    path = tmp_path / 'artifact-loop.yaml'
    compiler.Compiler().compile(pipeline, str(path))
    templates = yaml.safe_load(path.read_text())['spec']['templates']
    consumer = next(t for t in templates if t.get('initContainers'))
    assert sum('container' in t for t in templates) == 2
    assert any(
        p['name'] == 'kfp-meta-data' for p in consumer['inputs']['parameters']
    )
    args = consumer['container']['args']
    contract = json.loads(args[args.index('--argo_input') + 1])
    assert contract['inputs']['data']['stagedArtifact'] is True


def test_raw_container_list_uses_native_args_file_without_a_new_pod(tmp_path):
    @dsl.container_component
    def raw(values: dsl.Input[List[dsl.Dataset]], output: dsl.OutputPath(int)):
        return dsl.ContainerSpec(
            image='python:3.11',
            command=['python3', '-c', 'import sys'],
            args=[values, output],
        )

    @dsl.pipeline
    def pipeline():
        with dsl.ParallelFor([1, 2]) as item:
            data = produce(value=item)
        raw(values=dsl.Collected(data.outputs['data']))

    path = tmp_path / 'raw-list.yaml'
    compiler.Compiler().compile(pipeline, str(path))
    templates = yaml.safe_load(path.read_text())['spec']['templates']
    assert sum('container' in t for t in templates) == 2
    consumer = next(t for t in templates if t.get('initContainers'))
    assert consumer['container']['command'] == ['python3']
    assert any(
        e['name'] == 'ARGO_CONTAINER_ARGS_FILE'
        for e in consumer['container']['env']
    )
    assert any(
        a['name'] == 'kfp-staging-args' for a in consumer['inputs']['artifacts']
    )
    assert any(
        a['name'] == 'kfp-metadata' for a in consumer['outputs']['artifacts']
    )
    from kfp.compiler.argo_artifact_lists import bind_repository

    spec = yaml.safe_load(path.read_text())['spec']
    bind_repository(
        spec,
        {
            's3': {
                'endpoint': 'storage',
                'accessKeySecret': {'name': 'storage', 'key': 'access'},
            }
        },
    )
    wrapper = next(
        t
        for t in templates
        if t.get('metadata', {})
        .get('annotations', {})
        .get('pipelines.kubeflow.org/component-wrapper')
        == 'true'
    )
    assert all('path' not in a for a in wrapper['inputs'].get('artifacts', []))
    assert (
        'pipelines.kubeflow.org/artifact-list-staging'
        not in wrapper['metadata']['annotations']
    )


def test_importer_collection_identity_carries_inline_metadata(tmp_path):
    @dsl.pipeline
    def pipeline():
        with dsl.ParallelFor([0]):
            item = dsl.importer(
                artifact_uri='https://example.test/data',
                artifact_class=dsl.Dataset,
                metadata={'origin': 'external'},
            )
        consume(values=dsl.Collected(item.output))

    path = tmp_path / 'imported.yaml'
    compiler.Compiler().compile(pipeline, str(path))
    templates = yaml.safe_load(path.read_text())['spec']['templates']
    importer = next(
        t
        for t in templates
        if any(
            a.get('name') == 'metadata' and 'raw' in a
            for a in t.get('inputs', {}).get('artifacts', [])
        )
    )
    raw = next(
        a['raw']['data']
        for a in importer['inputs']['artifacts']
        if a['name'] == 'metadata'
    )
    identity = next(
        p['valueFrom']['expression']
        for p in importer['outputs']['parameters']
        if p['name'] == 'kfp-meta-artifact'
    )
    assert identity == raw[3:-2], (
        'A virtual importer has no metadata file for the stager to fetch'
    )


def test_repository_binding_projects_only_selected_keys_into_init(tmp_path):
    from kfp.compiler.argo_artifact_lists import bind_repository

    path = tmp_path / 'list.yaml'
    compiler.Compiler().compile(collected_pipeline, str(path))
    spec = yaml.safe_load(path.read_text())['spec']
    consumer = next(t for t in spec['templates'] if t.get('initContainers'))
    main_before = copy.deepcopy(consumer['container'])
    repository = {
        's3': {
            'endpoint': 'minio:9000',
            'accessKeySecret': {'name': 'storage', 'key': 'access'},
            'secretKeySecret': {'name': 'storage', 'key': 'secret'},
        }
    }
    bind_repository(spec, repository)
    bind_repository(spec, repository)
    assert consumer['container'] == main_before
    volumes = [v for v in consumer['volumes'] if 'secret' in v]
    assert len(volumes) == 1
    assert volumes[0]['secret']['items'] == [
        {'key': 'access', 'path': 'access'},
        {'key': 'secret', 'path': 'secret'},
    ]
    init = consumer['initContainers'][0]
    assert any(
        m['name'] == volumes[0]['name'] and m['readOnly']
        for m in init['volumeMounts']
    )
    assert all(
        m['name'] != volumes[0]['name']
        for m in consumer['container']['volumeMounts']
    )
    shared = json.loads(consumer['podSpecPatch'])['initContainers'][0][
        'volumeMounts'
    ][0]
    assert shared == {
        'name': 'var-run-argo',
        'mountPath': '/kfp-argo-binary',
        'readOnly': True,
    }
    bound = json.loads(
        next(
            e['value']
            for e in init['env']
            if e['name'] == 'KFP_STAGING_REPOSITORY'
        )
    )
    assert bound == repository
