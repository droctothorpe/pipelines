# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0

import json
from unittest.mock import patch

import pytest
import yaml

from kfp import compiler, dsl
from kfp.dsl.types.type_utils import InconsistentTypeException


@dsl.component(base_image='python:3.11', install_kfp_package=False)
def identity(value: int) -> int:
    return value


def test_yaml_preserves_single_letter_boolean_like_strings(tmp_path):
    @dsl.pipeline
    def pipeline(n: int = 1):
        identity(value=n)

    path = tmp_path / 'n.yaml'
    compiler.Compiler().compile(pipeline, str(path))
    assert "name: 'n'" in path.read_text(), (
        'Argo YAML 1.1 treats bare n as a boolean'
    )
    assert (
        yaml.safe_load(path.read_text())['spec']['arguments']['parameters'][0][
            'name'
        ]
        == 'n'
    )


def test_decorator_captures_without_building_ir(tmp_path):
    with patch(
        'kfp.dsl.structures.ComponentSpec.to_pipeline_spec',
        side_effect=AssertionError('IR builder called'),
    ):

        @dsl.pipeline(name='native-test')
        def pipeline(value: int = 3):
            identity(value=value).set_caching_options(False)

        compiler.Compiler().compile(pipeline, str(tmp_path / 'pipeline.yaml'))
    manifest = yaml.safe_load((tmp_path / 'pipeline.yaml').read_text())
    assert manifest['kind'] == 'WorkflowTemplate'
    assert manifest['apiVersion'] == 'argoproj.io/v1alpha1'
    assert 'pipelineSpec' not in str(manifest)
    task = next(t for t in manifest['spec']['templates'] if 'container' in t)
    assert '--argo_input' in task['container']['args']
    assert '--executor_input' not in task['container']['args']


def test_type_check_is_preserved():
    with pytest.raises(InconsistentTypeException, match='Incompatible'):

        @dsl.pipeline
        def invalid():
            identity(value='wrong')


def test_workflow_and_cron_are_explicit(tmp_path):
    @dsl.pipeline(name='native-kinds')
    def pipeline(value: int = 1):
        identity(value=value).set_caching_options(False)

    for kind in ('Workflow', 'CronWorkflow'):
        path = tmp_path / f'{kind}.yaml'
        compiler.Compiler().compile(
            pipeline,
            str(path),
            resource_kind=kind,
            schedule='0 9 * * *' if kind == 'CronWorkflow' else None,
        )
        manifest = yaml.safe_load(path.read_text())
        assert manifest['kind'] == kind
        if kind == 'CronWorkflow':
            assert manifest['spec']['schedules'] == ['0 9 * * *']
            assert manifest['spec']['suspend'] is True


def test_conditions_loops_and_collection(tmp_path):
    @dsl.component(base_image='python:3.11', install_kfp_package=False)
    def total(values: list) -> int:
        return sum(values)

    @dsl.pipeline(name='native-control-flow')
    def pipeline(value: int = 2):
        with dsl.If(value > 0):
            identity(value=value).set_caching_options(False)
        with dsl.Else():
            identity(value=0).set_caching_options(False)
        with dsl.ParallelFor([1, 2, 3], parallelism=2) as item:
            result = identity(value=item).set_caching_options(False)
        total(values=dsl.Collected(result.output)).set_caching_options(False)

    path = tmp_path / 'control.yaml'
    compiler.Compiler().compile(pipeline, str(path), resource_kind='Workflow')
    manifest = yaml.safe_load(path.read_text())
    templates = manifest['spec']['templates']
    assert any(t.get('parallelism') == 2 for t in templates)
    assert any(
        'withParam' in task
        for t in templates
        for task in t.get('dag', {}).get('tasks', [])
    )
    assert (
        sum(
            'when' in task
            for t in templates
            for task in t.get('dag', {}).get('tasks', [])
        )
        == 2
    )


def test_loop_item_fields_decode_object_and_json_string_items(tmp_path):
    """Regression: `fromJSON(item)` fails Argo's type check when the loop item
    is already a decoded object (samples/core loop_parallelism, loop_parameter).
    The projection must serialize before decoding so both shapes evaluate."""

    @dsl.component(base_image='python:3.11', install_kfp_package=False)
    def show(value: int):
        print(value)

    @dsl.pipeline(name='native-loop-items')
    def pipeline():
        with dsl.ParallelFor([{'a': 1, 'b': 2}, {'a': 10, 'b': 20}]) as item:
            show(value=item.a)
            show(value=item.b)

    path = tmp_path / 'loop.yaml'
    compiler.Compiler().compile(pipeline, str(path), resource_kind='Workflow')
    values = [
        parameter['value']
        for t in yaml.safe_load(path.read_text())['spec']['templates']
        for task in t.get('dag', {}).get('tasks', [])
        for parameter in task.get('arguments', {}).get('parameters', [])
        if '{{=' in parameter['value']
    ]
    assert len(values) == 2, values
    for value in values:
        assert 'fromJSON(item)' not in value, value
        assert (
            "fromJSON(type(item) == 'string' ? item : toJson(item))" in value
        ), value


def test_pvc_tasks_keep_static_commands_despite_nullable_inputs(tmp_path):
    """Regression: CreatePVC/DeletePVC inputs are nullable, which routed the
    synthetic Python stub through the dynamic argv patch; Argo then failed with
    "Error applying PodSpecPatch" (samples/core/kubernetes_pvc). The stub reads
    the whole parameter map, so it needs no presence-dependent argv."""
    from kfp import kubernetes

    @dsl.component(base_image='python:3.11', install_kfp_package=False)
    def touch():
        pass

    @dsl.pipeline(name='native-pvc')
    def pipeline():
        claim = kubernetes.CreatePVC(
            pvc_name_suffix='-data', access_modes=['ReadWriteOnce'], size='1Mi'
        )
        task = touch()
        kubernetes.mount_pvc(
            task, pvc_name=claim.outputs['name'], mount_path='/data'
        )
        kubernetes.DeletePVC(pvc_name=claim.outputs['name']).after(task)

    path = tmp_path / 'pvc.yaml'
    compiler.Compiler().compile(pipeline, str(path), resource_kind='Workflow')
    stubs = [
        t
        for t in yaml.safe_load(path.read_text())['spec']['templates']
        if t.get('container', {}).get('args', [])[:1]
        in (['create'], ['delete'])
    ]
    assert len(stubs) == 2, [t['name'] for t in stubs]
    encoded = {}
    for template in stubs:
        assert 'podSpecPatch' not in template, template['name']
        args = template['container']['args']
        assert args[1:3] == ['{{inputs.parameters}}', '{{workflow.namespace}}']
        encoded[args[0]] = json.loads(args[3])
    # The stub decodes exactly the parameters the compiler JSON-encodes: lists,
    # dictionaries and nullable inputs. DeletePVC's required name stays raw.
    assert encoded['create'] == [
        'access_modes',
        'annotations',
        'data_source',
        'pvc_name',
        'pvc_name_suffix',
        'storage_class_name',
        'volume_name',
    ]
    assert encoded['delete'] == []


def test_caching_accepts_tags_and_honors_optional_image_identity(tmp_path):
    @dsl.pipeline(name='cache-test')
    def pipeline(value: int = 1):
        identity(value=value)

    path = tmp_path / 'cache.yaml'
    compiler.Compiler().compile(pipeline, str(path))
    tagged = next(
        t
        for t in yaml.safe_load(path.read_text())['spec']['templates']
        if 'container' in t
    )
    assert tagged['container']['image'] == 'python:3.11'
    assert 'memoize' in tagged
    compiler.Compiler(
        image_digests={'python:3.11': 'sha256:' + 'a' * 64}
    ).compile(pipeline, str(path))
    template = next(
        t
        for t in yaml.safe_load(path.read_text())['spec']['templates']
        if 'container' in t
    )
    assert 'toJson(inputs.parameters)' in template['memoize']['key']
    assert template['container']['image'] == 'python:kfp-' + 'a' * 64
    assert template['memoize']['key'] != tagged['memoize']['key']


@pytest.mark.parametrize(
    'image,repository',
    [
        ('repo/image:dev', 'repo/image'),
        ('localhost:5000/image:dev', 'localhost:5000/image'),
        ('image', 'image'),
    ],
)
def test_local_image_snapshot_reference(image, repository):
    from kfp.compiler.argo_compiler import local_image_reference

    assert (
        local_image_reference(image, 'sha256:' + 'a' * 64)
        == repository + ':kfp-' + 'a' * 64
    )


def test_cache_allows_runtime_package_installation(tmp_path):
    @dsl.component(base_image='python@sha256:' + 'a' * 64)
    def installed(value: int) -> int:
        return value

    @dsl.pipeline(name='installed-cache')
    def pipeline():
        installed(value=1)

    path = tmp_path / 'pipeline.yaml'
    compiler.Compiler().compile(pipeline, str(path))
    template = next(
        t
        for t in yaml.safe_load(path.read_text())['spec']['templates']
        if 'container' in t
    )
    assert 'memoize' in template
    assert any(
        'PIP_DISABLE_PIP_VERSION_CHECK=1' in command
        for command in template['container']['command']
    )


def test_cache_preserves_explicit_external_configuration(tmp_path):
    from kfp import kubernetes

    @dsl.pipeline(name='mutable-cache')
    def pipeline():
        task = identity(value=1)
        kubernetes.use_secret_as_env(task, 'mutable-secret', {'key': 'VALUE'})

    path = tmp_path / 'pipeline.yaml'
    compiler.Compiler().compile(pipeline, str(path))
    template = next(
        t
        for t in yaml.safe_load(path.read_text())['spec']['templates']
        if 'container' in t
    )
    assert 'memoize' in template
    assert any(
        item.get('valueFrom', {}).get('secretKeyRef', {}).get('name')
        == 'mutable-secret'
        for item in template['container']['env']
    )


def test_retry_normalizes_integral_float_factor_and_duration_aliases(tmp_path):
    @dsl.pipeline(name='retry-normalization')
    def pipeline():
        identity(value=1).set_retry(
            1, backoff_factor=2.0, backoff_duration='2 minutes'
        ).set_caching_options(False)

    path = tmp_path / 'retry.yaml'
    compiler.Compiler().compile(pipeline, str(path))
    template = next(
        t
        for t in yaml.safe_load(path.read_text())['spec']['templates']
        if 'container' in t
    )
    assert template['retryStrategy']['backoff']['factor'] == '2'
    assert template['retryStrategy']['backoff']['duration'] == '120s'


def test_default_retry_covers_direct_component_failures(tmp_path):
    @dsl.pipeline(name='retry-direct-failure')
    def pipeline():
        identity(value=1).set_retry(2)

    compiler.Compiler().compile(pipeline, str(tmp_path / 'retry.yaml'))
    manifest = yaml.safe_load((tmp_path / 'retry.yaml').read_text())
    task = next(
        template
        for template in manifest['spec']['templates']
        if 'container' in template
    )
    assert task['retryStrategy']['limit'] == '2'
    assert task['retryStrategy']['retryPolicy'] == 'Always'


def test_retry_rejects_fractional_factor(tmp_path):
    @dsl.pipeline(name='fractional-retry')
    def pipeline():
        identity(value=1).set_retry(1, backoff_factor=2.5).set_caching_options(
            False
        )

    with pytest.raises(ValueError, match='integer backoff_factor'):
        compiler.Compiler().compile(pipeline, str(tmp_path / 'retry.yaml'))


def test_dynamic_resources_bind_native_inputs_and_patch_quantities(tmp_path):
    @dsl.pipeline(name='dynamic-resource')
    def pipeline(cpu: str = '100m'):
        identity(value=1).set_cpu_request(cpu).set_caching_options(False)

    compiler.Compiler().compile(pipeline, str(tmp_path / 'pipeline.yaml'))
    manifest = yaml.safe_load((tmp_path / 'pipeline.yaml').read_text())
    task = next(
        item for item in manifest['spec']['templates'] if 'container' in item
    )
    assert 'resources' not in task['container']
    assert '{{inputs.parameters.kfp-config-0}}' in task['podSpecPatch']
    root = next(item for item in manifest['spec']['templates'] if 'dag' in item)
    assert {
        'name': 'kfp-config-0',
        'value': '{{inputs.parameters.cpu}}',
    } in root['dag']['tasks'][0]['arguments']['parameters']


def test_resources_and_kubernetes_configuration(tmp_path):
    from kfp import kubernetes

    @dsl.pipeline(name='configuration')
    def pipeline():
        task = identity(value=1).set_caching_options(False)
        task.set_cpu_request('100m').set_memory_limit('128Mi').set_retry(
            2, policy='OnFailure'
        )
        kubernetes.add_node_selector(task, 'pool', 'cpu')
        kubernetes.use_secret_as_env(task, 'my-secret', {'key': 'TOKEN'})
        kubernetes.add_toleration(task, key='pool', operator='Exists')

    path = tmp_path / 'config.yaml'
    compiler.Compiler().compile(pipeline, str(path))
    template = next(
        t
        for t in yaml.safe_load(path.read_text())['spec']['templates']
        if 'container' in t
    )
    assert template['container']['resources'] == {
        'requests': {'cpu': '100m'},
        'limits': {'memory': '128Mi'},
    }
    assert template['retryStrategy']['retryPolicy'] == 'OnFailure'
    assert template['nodeSelector'] == {'pool': 'cpu'}
    assert (
        template['container']['env'][-1]['valueFrom']['secretKeyRef']['name']
        == 'my-secret'
    )


def test_exit_handler_is_failure_aware_native_dag(tmp_path):
    @dsl.component(base_image='python:3.11', install_kfp_package=False)
    def report(status: dsl.PipelineTaskFinalStatus):
        print(status.state)

    @dsl.pipeline(name='exit-test')
    def pipeline():
        handler = report().set_caching_options(False)
        with dsl.ExitHandler(handler):
            identity(value=1).set_caching_options(False)

    path = tmp_path / 'exit.yaml'
    compiler.Compiler().compile(pipeline, str(path))
    manifest = yaml.safe_load(path.read_text())
    wrapper = next(
        t
        for t in manifest['spec']['templates']
        if t.get('dag', {}).get('failFast') is False
    )
    assert wrapper['dag']['target'] == 'body exit'
    cleanup = wrapper['dag']['tasks'][1]
    assert cleanup['depends'] == 'body.Succeeded || body.Failed || body.Errored'
    assert 'SUCCEEDED' in cleanup['arguments']['parameters'][0]['value']
    assert 'FAILED' in cleanup['arguments']['parameters'][0]['value']
    target = next(
        t
        for t in manifest['spec']['templates']
        if t['name'] == cleanup['template']
    )
    assert {'name': 'status'} in target['inputs']['parameters']
    args = target['container']['args']
    import json

    assert (
        'status' in json.loads(args[args.index('--argo_input') + 1])['inputs']
    )


@pytest.mark.parametrize('grouped', [False, True])
def test_ignore_upstream_failure_preserves_defaults_and_failed_run(
    tmp_path, grouped
):
    @dsl.component
    def cleanup(message: str = 'fallback') -> str:
        return message

    @dsl.pipeline
    def pipeline(enabled: bool = True):
        def body():
            source = cleanup(message='upstream')
            cleanup(message=source.output).ignore_upstream_failure()

        if grouped:
            with dsl.If(enabled == True):
                body()
        else:
            body()

    path = tmp_path / 'cleanup.yaml'
    compiler.Compiler().compile(pipeline, str(path))
    templates = yaml.safe_load(path.read_text())['spec']['templates']
    dag = next(
        t['dag']
        for t in templates
        if any(
            task['name'] == 'cleanup-2'
            for task in t.get('dag', {}).get('tasks', [])
        )
    )
    task = next(task for task in dag['tasks'] if task['name'] == 'cleanup-2')
    assert 'dependencies' not in task
    assert 'cleanup.Failed' in task['depends']
    assert 'cleanup.Errored' in task['depends']
    assert dag['failFast'] is False
    assert set(dag['target'].split()) == {'cleanup', 'cleanup-2'}
    args = {p['name']: p['value'] for p in task['arguments']['parameters']}
    assert 'Succeeded' in args['message']
    assert ' ?? ' in args['message'], (
        'Argo must not require absent outputs before evaluating the fallback'
    )


def test_ignore_upstream_failure_supplies_final_status(tmp_path):
    @dsl.component
    def cleanup(status: dsl.PipelineTaskFinalStatus):
        print(status.state)

    @dsl.pipeline
    def pipeline():
        source = identity(value=1)
        cleanup().after(source).ignore_upstream_failure()

    path = tmp_path / 'final-status.yaml'
    compiler.Compiler().compile(pipeline, str(path))
    templates = yaml.safe_load(path.read_text())['spec']['templates']
    task = next(
        task
        for template in templates
        for task in template.get('dag', {}).get('tasks', [])
        if task['name'] == 'cleanup'
    )
    status = next(
        item['value']
        for item in task['arguments']['parameters']
        if item['name'] == 'status'
    )
    assert 'FAILED' in status
    assert 'SUCCEEDED' in status
    assert 'identity' in status


def test_ignore_upstream_failure_without_dependencies_is_noop(tmp_path):
    @dsl.pipeline
    def pipeline():
        identity(value=1).ignore_upstream_failure()

    path = tmp_path / 'noop.yaml'
    compiler.Compiler().compile(pipeline, str(path))
    root = yaml.safe_load(path.read_text())['spec']['templates'][0]['dag']
    assert 'depends' not in root['tasks'][0]
    assert 'failFast' not in root


@pytest.mark.parametrize('kind', [int, float, bool, list, dict])
def test_container_scalar_outputs_use_native_validation(tmp_path, kind):
    @dsl.container_component
    def integer_output(value: dsl.OutputPath(kind)):
        return dsl.ContainerSpec(
            image='busybox:1.36.1',
            command=['sh', '-c'],
            args=['echo not-an-integer > "$1"', 'component', value],
        )

    @dsl.pipeline(name='typed-output')
    def pipeline():
        integer_output().set_caching_options(False)

    path = tmp_path / 'pipeline.yaml'
    compiler.Compiler().compile(pipeline, str(path))
    templates = yaml.safe_load(path.read_text())['spec']['templates']
    assert sum('container' in t for t in templates) == 1
    wrapper = next(
        t
        for t in templates
        if t.get('metadata', {})
        .get('annotations', {})
        .get('pipelines.kubeflow.org/component-wrapper')
        == 'true'
    )
    output = next(
        p for p in wrapper['outputs']['parameters'] if p['name'] == 'value'
    )
    assert 'expression' in output['valueFrom']
    assert 'execute' in output['valueFrom']['expression']
    validation = next(t for t in templates if 'suspend' in t)
    assert validation['suspend'] == {'duration': '0'}
    assert wrapper['dag']['tasks'][-1]['dependencies'] == ['execute']
    assert next(t for t in templates if 'container' in t)['container'][
        'command'
    ] == ['sh', '-c']


def test_metadata_port_paths_and_storage_keys_do_not_collide(tmp_path):
    @dsl.component(base_image='python:3.11', install_kfp_package=False)
    def make(metadata: dsl.Output[dsl.Artifact]):
        with open(metadata.path, 'w') as stream:
            stream.write('payload')

    @dsl.pipeline(name='metadata-paths')
    def pipeline():
        make().set_caching_options(False)

    path = tmp_path / 'pipeline.yaml'
    compiler.Compiler().compile(pipeline, str(path))
    template = next(
        t
        for t in yaml.safe_load(path.read_text())['spec']['templates']
        if 'container' in t
    )
    artifacts = template['outputs']['artifacts']
    assert len({artifact['path'] for artifact in artifacts}) == len(artifacts)
    assert len({artifact['s3']['key'] for artifact in artifacts}) == len(
        artifacts
    )
    identity = next(
        parameter
        for parameter in template['outputs']['parameters']
        if parameter['name'] == 'kfp-meta-metadata'
    )
    assert identity['valueFrom']['path'] == '/tmp/kfp/identities/metadata.json'


def test_nested_pipeline_outputs(tmp_path):
    @dsl.pipeline(name='nested-inner')
    def inner(value: int) -> int:
        return identity(value=value).set_caching_options(False).output

    @dsl.pipeline(name='nested-outer')
    def outer(value: int = 3):
        first = inner(value=value)
        identity(value=first.output).set_caching_options(False)

    path = tmp_path / 'nested.yaml'
    compiler.Compiler().compile(outer, str(path))
    manifest = yaml.safe_load(path.read_text())
    assert (
        sum('dag' in template for template in manifest['spec']['templates'])
        == 2
    )


def test_oneof_merges_conditional_parameter_outputs(tmp_path):
    @dsl.pipeline(name='oneof-compatibility')
    def pipeline(choice: bool = True) -> int:
        with dsl.If(choice == True):
            left = identity(value=3)
        with dsl.Else():
            right = identity(value=7)
        return identity(value=dsl.OneOf(left.output, right.output)).output

    compiler.Compiler().compile(pipeline, str(tmp_path / 'pipeline.yaml'))
    manifest = yaml.safe_load((tmp_path / 'pipeline.yaml').read_text())
    expressions = [
        parameter.get('valueFrom', {}).get('expression', '')
        for template in manifest['spec']['templates']
        for parameter in template.get('outputs', {}).get('parameters', [])
    ]
    assert any(
        '.status' in expression and '.outputs.parameters' in expression
        for expression in expressions
    )


def test_root_input_return_uses_expression_not_literal_parameter_lookup(
    tmp_path,
):
    @dsl.pipeline(name='input-return')
    def pipeline(value: int = 7) -> int:
        identity(value=value)
        return value

    compiler.Compiler().compile(pipeline, str(tmp_path / 'pipeline.yaml'))
    manifest = yaml.safe_load((tmp_path / 'pipeline.yaml').read_text())
    root = next(
        template
        for template in manifest['spec']['templates']
        if template['name'] == manifest['spec']['entrypoint']
    )
    assert root['outputs']['parameters'][0]['valueFrom'] == {
        'expression': 'inputs.parameters["value"]'
    }


def test_compile_type_check_false_preserves_valid_programs_and_relaxes_defaults(
    tmp_path,
):
    import kfp

    @dsl.pipeline(name='unchecked-default')
    def pipeline(value: int = 7):
        identity(value=value)

    previous = kfp.TYPE_CHECK
    compiler.Compiler().compile(
        pipeline,
        str(tmp_path / 'pipeline.yaml'),
        pipeline_parameters={'value': 'unchecked'},
        type_check=False,
    )
    assert kfp.TYPE_CHECK == previous
    manifest = yaml.safe_load((tmp_path / 'pipeline.yaml').read_text())
    assert (
        manifest['spec']['arguments']['parameters'][0]['value'] == '"unchecked"'
    )
    with pytest.raises(ValueError, match='Integer'):
        compiler.Compiler().compile(
            pipeline,
            str(tmp_path / 'checked.yaml'),
            pipeline_parameters={'value': 'unchecked'},
        )
    assert kfp.TYPE_CHECK == previous


def test_versions_are_content_addressed(tmp_path):
    @dsl.pipeline(name='native-version')
    def pipeline(value: int = 1):
        identity(value=value).set_caching_options(False)

    names = []
    for value in (1, 1, 2):
        path = tmp_path / 'version.yaml'
        compiler.Compiler().compile(
            pipeline, str(path), pipeline_parameters={'value': value}
        )
        names.append(yaml.safe_load(path.read_text())['metadata']['name'])
    assert names[0] == names[1]
    assert names[1] != names[2]
