# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Compile-time validation ported from stock's ``compiler_test.py``.

Stock inspected the PipelineSpec IR; these tests inspect the native Argo
manifest instead. Authoring-time errors raised by ``kfp.dsl`` are asserted
unchanged. Where native behavior departs from stock, the test is a strict
xfail naming the ``docs/compatibility.md`` row or the compiler gap.
"""

import json
from typing import List, Optional

import pytest
import yaml

from kfp import compiler, components, dsl
from kfp.dsl import Artifact, Input, Model, Output, PipelineTaskFinalStatus
from kfp.dsl.types import type_utils

LOOP_ESCAPE = 'must be wrapped in dsl.Collected'
CONDITION_ESCAPE = 'Conditional output escapes its branch'


@dsl.component
def print_and_return(text: str) -> str:
    print(text)
    return text


@dsl.component
def print_op(message: str):
    print(message)


@dsl.component
def dummy_op(msg: str = ''):
    pass


@dsl.component
def double(num: int) -> int:
    return 2 * num


@dsl.component
def add(nums: List[int]) -> int:
    return sum(nums)


@dsl.component
def print_hello():
    print('hello')


@dsl.component
def my_comp(string: str, model: bool) -> str:
    return string


def compile_manifest(pipeline_func, tmp_path, **kwargs):
    path = tmp_path / 'pipeline.yaml'
    compiler.Compiler().compile(pipeline_func, str(path), **kwargs)
    return yaml.safe_load(path.read_text())


def templates(manifest):
    return {t['name']: t for t in manifest['spec']['templates']}


def root_template(manifest):
    return templates(manifest)[manifest['spec']['entrypoint']]


def dag_tasks(template):
    return {task['name']: task for task in template['dag']['tasks']}


def depends_on(manifest, consumer, upstream):
    """A23: a dependency into a group is lifted onto that group in the DAG
    that owns the consumer."""
    dag = template_with_task(manifest, consumer)
    assert upstream in dag_tasks(dag)[consumer].get('dependencies', []), (
        dag_tasks(dag)[consumer]
    )


def template_with_task(manifest, task_name):
    return next(
        t
        for t in manifest['spec']['templates']
        if 'dag' in t and task_name in dag_tasks(t)
    )


def parameters(section):
    return {
        p['name']: p.get('value', p.get('default'))
        for p in (section or {}).get('parameters', [])
    }


class TestCompileBadInput:
    @pytest.mark.parametrize('bad', [lambda x: x, 1, None])
    def test_compile_non_component_raises(self, tmp_path, bad):
        with pytest.raises(
            ValueError, match='Expected a component or pipeline'
        ):
            compiler.Compiler().compile(
                pipeline_func=bad, package_path=str(tmp_path / 'out.yaml')
            )


class TestWriteToFileTypes:
    pipeline_name = 'test-pipeline'

    def make_pipeline(self):
        @dsl.pipeline(name=self.pipeline_name)
        def my_pipeline():
            dummy_op()

        return my_pipeline

    @pytest.mark.parametrize('extension', ['.yaml', '.yml'])
    def test_can_write_to_yaml(self, tmp_path, extension):
        target = tmp_path / f'result{extension}'
        compiler.Compiler().compile(
            pipeline_func=self.make_pipeline(), package_path=str(target)
        )
        manifest = yaml.safe_load(target.read_text())
        assert manifest['kind'] == 'WorkflowTemplate'
        assert (
            manifest['metadata']['labels']['pipelines.kubeflow.org/pipeline']
            == self.pipeline_name
        )

    @pytest.mark.xfail(
        strict=True,
        reason='A21: Compiler.compile() writes Argo YAML to any path, '
        'including .json, with no deprecation warning or JSON payload.',
    )
    def test_can_write_to_json(self, tmp_path):
        target = tmp_path / 'result.json'
        with pytest.warns(
            DeprecationWarning, match='Compiling to JSON is deprecated'
        ):
            compiler.Compiler().compile(
                pipeline_func=self.make_pipeline(), package_path=str(target)
            )
        json.loads(target.read_text())

    def test_json_path_receives_argo_yaml(self, tmp_path):
        """A21: the documented native behavior for a .json target."""
        target = tmp_path / 'result.json'
        compiler.Compiler().compile(
            pipeline_func=self.make_pipeline(), package_path=str(target)
        )
        assert target.read_text().startswith('apiVersion: argoproj.io/')

    @pytest.mark.xfail(
        strict=True,
        reason='A21: Compiler.compile() writes Argo YAML to any path; stock '
        'rejected extensions other than .yaml/.yml/.json.',
    )
    def test_cannot_write_to_bad_extension(self, tmp_path):
        with pytest.raises(ValueError, match=r'should end with "\.yaml"'):
            compiler.Compiler().compile(
                pipeline_func=self.make_pipeline(),
                package_path=str(tmp_path / 'result.bad_extension'),
            )

    def test_compile_pipeline_with_default_value(self, tmp_path):
        @dsl.container_component
        def producer_op(
            nodefault: str, location: str = 'us-central1', name: int = 1
        ):
            return dsl.ContainerSpec(
                image='gcr.io/my-project/my-image:tag', args=[location]
            )

        @dsl.pipeline(name='test-pipeline')
        def simple_pipeline():
            producer_op(location='1', nodefault='string')

        manifest = compile_manifest(simple_pipeline, tmp_path)
        container = next(
            t for t in manifest['spec']['templates'] if 'container' in t
        )
        assert container['inputs']['parameters'] == [
            {'name': 'nodefault'},
            {'name': 'location', 'default': 'us-central1'},
            {'name': 'name', 'default': '1'},
        ]
        assert container['container']['args'] == [
            '{{inputs.parameters.location}}'
        ]
        task = dag_tasks(root_template(manifest))['producer-op']
        assert parameters(task['arguments']) == {
            'nodefault': 'string',
            'location': '1',
            'name': '1',
        }

    def test_compile_fails_with_bad_pipeline_func(self, tmp_path):
        with pytest.raises(
            ValueError, match='Expected a component or pipeline'
        ):
            compiler.Compiler().compile(
                pipeline_func=None, package_path=str(tmp_path / 'p.yaml')
            )


class TestTopologyValidation:
    def test_invalid_condition_1(self, tmp_path):
        @dsl.pipeline
        def my_pipeline(foo: str):
            with dsl.Condition(foo == 'bar'):
                one = print_and_return(text='foo')
            # one may never execute, so one.output is not available
            print_and_return(text=one.output)

        with pytest.raises(ValueError, match=CONDITION_ESCAPE):
            compile_manifest(my_pipeline, tmp_path)

    def test_dependency_into_condition_is_lifted(self, tmp_path):
        # Stock: InvalidTopologyException. Native (A23): depend on the group.
        @dsl.pipeline
        def my_pipeline(foo: str):
            with dsl.Condition(foo == 'bar'):
                one = print_and_return(text='foo')
            print_and_return(text='baz').after(one)

        depends_on(
            compile_manifest(my_pipeline, tmp_path),
            'print-and-return-2',
            'condition-1',
        )

    def test_dependency_into_nested_condition_is_lifted(self, tmp_path):
        @dsl.pipeline
        def my_pipeline(foo: str):
            with dsl.Condition(foo == 'bar'):
                with dsl.Condition(foo == 'bar'):
                    one = print_and_return(text='foo')
                print_and_return(text='baz').after(one)

        depends_on(
            compile_manifest(my_pipeline, tmp_path),
            'print-and-return-2',
            'condition-2',
        )

    def test_dependency_between_sibling_conditions_is_lifted(self, tmp_path):
        @dsl.pipeline
        def my_pipeline(foo: str):
            with dsl.Condition(foo == 'foo'):
                one = print_and_return(text='foo')
            with dsl.Condition(foo == 'bar'):
                print_and_return(text='bar').after(one)

        depends_on(
            compile_manifest(my_pipeline, tmp_path),
            'condition-2',
            'condition-1',
        )

    def test_valid_condition_1(self, tmp_path):
        @dsl.pipeline
        def my_pipeline(foo: str):
            with dsl.Condition(foo == 'bar'):
                one = print_and_return(text='foo')
                print_and_return(text=one.output)

        branch = template_with_task(
            compile_manifest(my_pipeline, tmp_path), 'print-and-return-2'
        )
        assert dag_tasks(branch)['print-and-return-2']['dependencies'] == [
            'print-and-return'
        ]

    def test_valid_condition_2(self, tmp_path):
        @dsl.pipeline
        def my_pipeline(foo: str):
            with dsl.Condition(foo == 'bar'):
                one = print_and_return(text='foo')
                print_and_return(text='baz').after(one)

        branch = template_with_task(
            compile_manifest(my_pipeline, tmp_path), 'print-and-return-2'
        )
        assert dag_tasks(branch)['print-and-return-2']['dependencies'] == [
            'print-and-return'
        ]

    def test_valid_condition_3(self, tmp_path):
        @dsl.pipeline
        def my_pipeline(foo: str):
            with dsl.Condition(foo == 'bar'):
                with dsl.Condition(foo == 'bar'):
                    one = print_and_return(text='foo')
                    print_and_return(text='baz').after(one)

        assert compile_manifest(my_pipeline, tmp_path)['spec']['templates']

    def test_valid_condition_4(self, tmp_path):
        """C28: the inner task's .after() on the outer task is lifted onto
        the inner condition group."""

        @dsl.pipeline
        def my_pipeline(foo: str):
            with dsl.Condition(foo == 'bar'):
                one = print_and_return(text='foo')
                with dsl.Condition(foo == 'bar'):
                    print_and_return(text='baz').after(one)

        outer = template_with_task(
            compile_manifest(my_pipeline, tmp_path), 'print-and-return'
        )
        assert dag_tasks(outer)['condition-2']['dependencies'] == [
            'print-and-return'
        ]

    def test_output_of_exit_handler_body_is_forwarded(self, tmp_path):
        @dsl.pipeline
        def my_pipeline(foo: str):
            exit_task = print_and_return(text='foo')
            with dsl.ExitHandler(exit_task=exit_task):
                one = print_and_return(text='foo')
            print_and_return(text=one.output)

        depends_on(
            compile_manifest(my_pipeline, tmp_path),
            'print-and-return-3',
            'exit-handler-1',
        )

    def test_dependency_into_exit_handler_is_lifted(self, tmp_path):
        @dsl.pipeline
        def my_pipeline(foo: str):
            exit_task = print_and_return(text='foo')
            with dsl.ExitHandler(exit_task=exit_task):
                one = print_and_return(text='foo')
            print_and_return(text='baz').after(one)

        depends_on(
            compile_manifest(my_pipeline, tmp_path),
            'print-and-return-3',
            'exit-handler-1',
        )

    def test_condition_consuming_exit_handler_output_is_lifted(self, tmp_path):
        @dsl.pipeline
        def my_pipeline(foo: str):
            exit_task = print_and_return(text='foo')
            with dsl.ExitHandler(exit_task=exit_task):
                one = print_and_return(text='foo')
            with dsl.Condition(foo == 'bar'):
                print_and_return(text=one.output)

        depends_on(
            compile_manifest(my_pipeline, tmp_path),
            'condition-2',
            'exit-handler-1',
        )

    def test_dependency_between_exit_handlers_is_lifted(self, tmp_path):
        @dsl.pipeline
        def my_pipeline():
            exit_task_1 = print_and_return(text='foo')
            with dsl.ExitHandler(exit_task_1):
                one = print_and_return(text='bar')
            exit_task_2 = print_and_return(text='baz')
            with dsl.ExitHandler(exit_task_2):
                print_and_return(text='bat').after(one)

        depends_on(
            compile_manifest(my_pipeline, tmp_path),
            'exit-handler-2',
            'exit-handler-1',
        )

    def test_valid_exithandler_1(self, tmp_path):
        @dsl.pipeline
        def my_pipeline(foo: str):
            exit_task = print_and_return(text='foo')
            with dsl.ExitHandler(exit_task=exit_task):
                one = print_and_return(text='foo')
                print_and_return(text=one.output)

        body = template_with_task(
            compile_manifest(my_pipeline, tmp_path), 'print-and-return-3'
        )
        assert dag_tasks(body)['print-and-return-3']['dependencies'] == [
            'print-and-return-2'
        ]

    def test_valid_exithandler_2(self, tmp_path):
        @dsl.pipeline
        def my_pipeline(foo: str):
            exit_task = print_and_return(text='foo')
            with dsl.ExitHandler(exit_task=exit_task):
                one = print_and_return(text='foo')
                print_and_return(text='baz').after(one)

        body = template_with_task(
            compile_manifest(my_pipeline, tmp_path), 'print-and-return-3'
        )
        assert dag_tasks(body)['print-and-return-3']['dependencies'] == [
            'print-and-return-2'
        ]

    def test_invalid_parallelfor_1(self, tmp_path):
        @dsl.pipeline
        def my_pipeline():
            with dsl.ParallelFor([1, 2, 3]):
                one = print_and_return(text='foo')
            print_and_return(text=one.output)

        with pytest.raises(ValueError, match=LOOP_ESCAPE):
            compile_manifest(my_pipeline, tmp_path)

    def test_invalid_parallelfor_2(self, tmp_path):
        @dsl.pipeline
        def my_pipeline(text: str):
            with dsl.ParallelFor([1, 2, 3]):
                one = print_and_return(text='foo')
            with dsl.Condition(text == 'foo'):
                print_and_return(text=one.output)

        with pytest.raises(ValueError, match=LOOP_ESCAPE):
            compile_manifest(my_pipeline, tmp_path)

    def test_invalid_parallelfor_3(self, tmp_path):
        @dsl.pipeline
        def my_pipeline():
            with dsl.ParallelFor([1, 2, 3]):
                one = print_and_return(text='foo')
            with dsl.ParallelFor([1, 2, 3]):
                print_and_return(text=one.output)

        with pytest.raises(ValueError, match=LOOP_ESCAPE):
            compile_manifest(my_pipeline, tmp_path)

    def test_valid_parallelfor_1(self, tmp_path):
        @dsl.pipeline
        def my_pipeline():
            with dsl.ParallelFor([1, 2, 3]):
                one = print_and_return(text='foo')
            with dsl.ParallelFor([1, 2, 3]):
                # refers to all instances of the task in the first loop
                print_and_return(text='bar').after(one)

        root = dag_tasks(root_template(compile_manifest(my_pipeline, tmp_path)))
        first, second = sorted(name for name in root if 'for-loop' in name)
        assert root[second]['dependencies'] == [first]
        assert 'dependencies' not in root[first]

    def test_valid_parallelfor_2(self, tmp_path):
        @dsl.pipeline
        def my_pipeline():
            one = print_and_return(text='foo')
            with dsl.ParallelFor([1, 2, 3]):
                print_and_return(text='bar').after(one)

        root = dag_tasks(root_template(compile_manifest(my_pipeline, tmp_path)))
        (loop,) = [name for name in root if 'for-loop' in name]
        assert root[loop]['dependencies'] == ['print-and-return']

    def test_valid_parallelfor_3(self, tmp_path):
        @dsl.pipeline
        def my_pipeline():
            with dsl.ParallelFor([1, 2, 3]):
                one = print_and_return(text='foo')
            print_and_return(text='bar').after(one)

        root = dag_tasks(root_template(compile_manifest(my_pipeline, tmp_path)))
        (loop,) = [name for name in root if 'for-loop' in name]
        assert root['print-and-return-2']['dependencies'] == [loop]

    def test_valid_parallelfor_4(self, tmp_path):
        @dsl.pipeline
        def my_pipeline():
            with dsl.ParallelFor([1, 2, 3]):
                with dsl.ParallelFor([1, 2, 3]):
                    one = print_and_return(text='foo')
                print_and_return(text='bar').after(one)

        outer = dag_tasks(
            template_with_task(
                compile_manifest(my_pipeline, tmp_path), 'print-and-return-2'
            )
        )
        (inner_loop,) = [name for name in outer if 'for-loop' in name]
        assert outer['print-and-return-2']['dependencies'] == [inner_loop]


class TestCannotReturnFromWithinControlFlowGroup:
    def test_condition_raises(self, tmp_path):
        @dsl.pipeline
        def my_pipeline(string: str = 'string') -> str:
            with dsl.Condition(string == 'foo'):
                return print_and_return(text=string).output

        with pytest.raises(ValueError, match=CONDITION_ESCAPE):
            compile_manifest(my_pipeline, tmp_path)

    def test_loop_raises(self, tmp_path):
        @dsl.pipeline
        def my_pipeline(string: str = 'string') -> str:
            with dsl.ParallelFor([1, 2, 3]):
                return print_and_return(text=string).output

        with pytest.raises(ValueError, match=LOOP_ESCAPE):
            compile_manifest(my_pipeline, tmp_path)

    def test_exit_handler_return_is_forwarded(self, tmp_path):
        """A31: stock refused a pipeline output from inside an ExitHandler;
        native forwards it through the exit wrapper (verified live in
        ``test/e2e/test_exit_handler_shapes.py``)."""

        @dsl.pipeline
        def my_pipeline(string: str = 'string') -> str:
            with dsl.ExitHandler(print_and_return(text='exit task')):
                return print_and_return(text=string).output

        manifest = compile_manifest(my_pipeline, tmp_path)
        root = root_template(manifest)
        (output,) = root['outputs']['parameters']
        assert output['name'] == 'Output'
        assert output['valueFrom']['parameter'].startswith(
            '{{tasks.exit-handler-1.outputs.parameters.'
        )


class TestCrossTasksGroupFanInCollection:
    def test_correct_subdag_return_type(self, tmp_path):
        @dsl.pipeline
        def math_pipeline() -> int:
            with dsl.ParallelFor([1, 2, 3]) as v:
                t = double(num=v)
            return add(nums=dsl.Collected(t.output)).output

        manifest = compile_manifest(math_pipeline, tmp_path)
        root = root_template(manifest)
        consumer = dag_tasks(root)['add']
        value = parameters(consumer['arguments'])['nums']
        assert value.startswith('{{tasks.for-loop-2.outputs.parameters.')
        channel = value[len('{{tasks.for-loop-2.outputs.parameters.') : -2]
        fanout = templates(manifest)[dag_tasks(root)['for-loop-2']['template']]
        (output,) = fanout['outputs']['parameters']
        # The fan-out wrapper aggregates iteration outputs into a list.
        assert output == {
            'name': channel,
            'valueFrom': {
                'parameter': '{{tasks.iteration.outputs.parameters.'
                + channel
                + '}}',
                'default': '[]',
            },
        }
        assert root['outputs']['parameters'] == [
            {
                'name': 'Output',
                'valueFrom': {
                    'parameter': '{{tasks.add.outputs.parameters.Output}}'
                },
            }
        ]

    def test_missing_collected_with_correct_annotation(self):
        with pytest.raises(
            type_utils.InconsistentTypeException,
            match="Argument type 'NUMBER_INTEGER' is incompatible with the input type 'LIST'",
        ):

            @dsl.pipeline
            def math_pipeline() -> int:
                with dsl.ParallelFor([1, 2, 3]) as v:
                    t = double(num=v)
                return add(nums=t.output).output

    def test_missing_collected_with_incorrect_annotation(self, tmp_path):
        @dsl.component
        def add_one(nums: int) -> int:
            return nums

        # The annotation is wrong, but the user did not use dsl.Collected.
        @dsl.pipeline
        def math_pipeline() -> int:
            with dsl.ParallelFor([1, 2, 3]) as v:
                t = double(num=v)
            return add_one(nums=t.output).output

        with pytest.raises(ValueError, match=LOOP_ESCAPE):
            compile_manifest(math_pipeline, tmp_path)

    def test_producer_condition_legal2(self, tmp_path):
        """L03: dsl.Collected from a producer under a condition inside the
        loop; skipped iterations are filtered out of the collection."""

        @dsl.pipeline
        def my_pipeline(a: str):
            with dsl.ParallelFor([1, 2, 3]) as v:
                with dsl.Condition(v == 1):
                    t = double(num=v)
            with dsl.Condition(a == 'a'):
                add(nums=dsl.Collected(t.output))

        manifest = compile_manifest(my_pipeline, tmp_path)
        named = templates(manifest)
        iteration = next(
            t for n, t in named.items() if n.endswith('for-loop-2')
        )
        (exported,) = iteration['outputs']['parameters']
        assert exported['valueFrom']['default'] == '__kfp_skipped_iteration__'
        assert exported['valueFrom']['parameter'].startswith(
            '{{tasks.condition-3.outputs.parameters.'
        )
        wrapper = next(
            t for n, t in named.items() if n.endswith('for-loop-2-fanout')
        )
        (aggregate,) = wrapper['outputs']['parameters']
        assert aggregate['valueFrom']['default'] == '[]'
        assert aggregate['valueFrom']['expression'].startswith(
            'toJson(filter(fromJSON(tasks["iteration"].outputs.parameters['
        )

    def test_collected_consumed_inside_condition(self, tmp_path):
        """L03: dsl.Collected consumed inside a condition from a loop at the
        pipeline root; the condition receives the collection as an input."""

        @dsl.pipeline
        def my_pipeline(a: str):
            with dsl.ParallelFor([1, 2, 3]) as v:
                t = double(num=v)
            with dsl.Condition(a == 'a'):
                add(nums=dsl.Collected(t.output))

        manifest = compile_manifest(my_pipeline, tmp_path)
        root = root_template(manifest)
        condition = dag_tasks(root)['condition-3']
        (argument,) = condition['arguments']['parameters']
        assert argument['value'].startswith(
            '{{tasks.for-loop-2.outputs.parameters.'
        )

    def test_producer_condition_illegal1(self, tmp_path):
        @dsl.pipeline
        def my_pipeline(a: str = '', b: str = ''):
            with dsl.Condition(a == 'a'):
                with dsl.ParallelFor([1, 2, 3]) as v:
                    t = double(num=v)
            with dsl.Condition(b == 'b'):
                add(nums=dsl.Collected(t.output))

        with pytest.raises(ValueError, match=CONDITION_ESCAPE):
            compile_manifest(my_pipeline, tmp_path)

    def test_producer_condition_illegal2(self, tmp_path):
        @dsl.pipeline
        def my_pipeline(a: str = ''):
            with dsl.Condition(a == 'a'):
                with dsl.ParallelFor([1, 2, 3]) as v:
                    t = double(num=v)
            add(nums=dsl.Collected(t.output))

        with pytest.raises(ValueError, match=CONDITION_ESCAPE):
            compile_manifest(my_pipeline, tmp_path)

    def test_collected_escapes_an_exit_handler(self, tmp_path):
        """A31: stock refused dsl.Collected from a loop inside an
        ExitHandler consumed outside it; native forwards the collection."""

        @dsl.component
        def exit_comp():
            print('Running exit task!')

        @dsl.pipeline
        def my_pipeline():
            with dsl.ExitHandler(exit_comp()):
                with dsl.ParallelFor([1, 2, 3]) as v:
                    t = double(num=v)
            add(nums=dsl.Collected(t.output))

        manifest = compile_manifest(my_pipeline, tmp_path)
        consumer = dag_tasks(root_template(manifest))['add']
        value = parameters(consumer['arguments'])['nums']
        assert value.startswith('{{tasks.exit-handler-1.outputs.parameters.')

    def test_parallelfor_nested_legal_params1(self, tmp_path):
        """L03: dsl.Collected across two loop levels consumed at the root
        arrives as a two-deep collection (List[List[int]])."""

        @dsl.component
        def add_two_ints(num1: int, num2: int) -> int:
            return num1 + num2

        @dsl.component
        def add_nested(nums: List[List[int]]) -> int:
            import itertools

            return sum(itertools.chain(*nums))

        @dsl.pipeline
        def my_pipeline():
            with dsl.ParallelFor([1, 2, 3]) as v1:
                with dsl.ParallelFor([1, 2, 3]) as v2:
                    t = add_two_ints(num1=v1, num2=v2)
            add_nested(nums=dsl.Collected(t.output))

        manifest = compile_manifest(my_pipeline, tmp_path)
        consumer = next(
            t
            for t in manifest['spec']['templates']
            if t.get('container') and 'add_nested' in str(t['container'])
        )
        args = consumer['container']['args']
        contract = json.loads(args[args.index('--argo_input') + 1])
        assert contract['inputs']['nums']['collectionDepth'] == 2

    def test_parallel_for_custom_name_with_collected(self, tmp_path):
        @dsl.component
        def echo(item: str) -> str:
            return item

        @dsl.component
        def collect(items: list) -> str:
            return str(items)

        @dsl.pipeline
        def my_pipeline():
            with dsl.ParallelFor(
                items=['a', 'b'], name='My custom Loop'
            ) as item:
                work = echo(item=item)
            collect(items=dsl.Collected(work.output))

        root = root_template(compile_manifest(my_pipeline, tmp_path))
        tasks = dag_tasks(root)
        # The downstream task references the stable DAG task key.
        assert 'for-loop-2' in tasks
        assert tasks['collect']['dependencies'] == ['for-loop-2']
        assert parameters(tasks['collect']['arguments'])['items'].startswith(
            '{{tasks.for-loop-2.outputs.parameters.'
        )

    def test_parallel_for_custom_name_is_recorded(self, tmp_path):
        @dsl.component
        def echo(item: str) -> str:
            return item

        @dsl.pipeline
        def my_pipeline():
            with dsl.ParallelFor(
                items=['a', 'b'], name='My custom Loop'
            ) as item:
                echo(item=item)

        manifest = compile_manifest(my_pipeline, tmp_path)
        assert 'My custom Loop' in yaml.dump(manifest)

    def test_parallelfor_nested_legal_params2(self, tmp_path):
        @dsl.component
        def add_two_ints(num1: int, num2: int) -> int:
            return num1 + num2

        @dsl.component
        def add_nested(nums: List[List[int]]) -> int:
            import itertools

            return sum(itertools.chain(*nums))

        @dsl.pipeline
        def my_pipeline():
            with dsl.ParallelFor([1, 2, 3]) as v1:
                with dsl.ParallelFor([1, 2, 3]) as v2:
                    t = add_two_ints(num1=v1, num2=v2)
                add_nested(nums=dsl.Collected(t.output))

        outer = dag_tasks(
            template_with_task(
                compile_manifest(my_pipeline, tmp_path), 'add-nested'
            )
        )
        (inner_loop,) = [name for name in outer if 'for-loop' in name]
        assert outer['add-nested']['dependencies'] == [inner_loop]
        assert parameters(outer['add-nested']['arguments'])['nums'].startswith(
            '{{tasks.' + inner_loop + '.outputs.parameters.'
        )

    def test_producer_and_consumer_in_same_context(self, tmp_path):
        @dsl.pipeline
        def math_pipeline():
            with dsl.ParallelFor([1, 2, 3]) as x:
                t = double(num=x)
                add(nums=dsl.Collected(t.output))

        with pytest.raises(ValueError):
            compile_manifest(math_pipeline, tmp_path)

    def test_no_parallelfor_context(self, tmp_path):
        @dsl.pipeline
        def math_pipeline():
            t = double(num=1)
            add(nums=dsl.Collected(t.output))

        with pytest.raises(ValueError):
            compile_manifest(math_pipeline, tmp_path)


class TestMultipleExitHandlerCompilation:
    def test_basic(self, tmp_path):
        @dsl.pipeline(name='pipeline-with-multiple-exit-handlers')
        def my_pipeline():
            first_exit_task = print_op(message='First exit task.')
            with dsl.ExitHandler(first_exit_task):
                print_op(message='Inside first exit handler.')

            second_exit_task = print_op(message='Second exit task.')
            with dsl.ExitHandler(second_exit_task):
                print_op(message='Inside second exit handler.')

        manifest = compile_manifest(my_pipeline, tmp_path)
        all_templates = templates(manifest)
        root = dag_tasks(root_template(manifest))
        assert set(root) == {'exit-handler-1', 'exit-handler-2'}
        for group, body_task, inside, exit_message in [
            ('exit-handler-1', 'print-op-2', 'Inside first', 'First'),
            ('exit-handler-2', 'print-op-4', 'Inside second', 'Second'),
        ]:
            wrapper = all_templates[root[group]['template']]
            tasks = dag_tasks(wrapper)
            assert set(tasks) == {'body', 'exit'}
            assert (
                tasks['exit']['depends']
                == 'body.Succeeded || body.Failed || body.Errored'
            )
            assert parameters(tasks['exit']['arguments']) == {
                'message': f'{exit_message} exit task.'
            }
            body = all_templates[tasks['body']['template']]
            assert parameters(dag_tasks(body)[body_task]['arguments']) == {
                'message': f'{inside} exit handler.'
            }

    def test_task_after_exit_handler_group(self, tmp_path):
        @dsl.pipeline(name='pipeline-after-exit-handler-group')
        def my_pipeline():
            exit_task = print_op(message='Exit task.')
            with dsl.ExitHandler(exit_task) as exit_group:
                print_op(message='Inside exit handler.')
            print_op(message='After exit handler.').after(exit_group)

        root = dag_tasks(root_template(compile_manifest(my_pipeline, tmp_path)))
        assert root['print-op-3']['dependencies'] == ['exit-handler-1']

    def test_tasks_after_multiple_exit_handler_groups(self, tmp_path):
        @dsl.pipeline(name='pipeline-after-multiple-exit-handler-groups')
        def my_pipeline():
            first_exit_task = print_op(message='First exit task.')
            with dsl.ExitHandler(first_exit_task) as first_exit_group:
                print_op(message='Inside first exit handler.')

            after_first = print_op(message='After first exit handler.').after(
                first_exit_group
            )

            second_exit_task = print_op(message='Second exit task.')
            with dsl.ExitHandler(second_exit_task) as second_exit_group:
                print_op(message='Inside second exit handler.').after(
                    after_first
                )

            print_op(message='After second exit handler.').after(
                second_exit_group
            )

        root = dag_tasks(root_template(compile_manifest(my_pipeline, tmp_path)))
        assert root['print-op-3']['dependencies'] == ['exit-handler-1']
        # C28: the inner .after() on an outside task lifts onto the group.
        assert root['exit-handler-2']['dependencies'] == ['print-op-3']
        assert root['print-op-6']['dependencies'] == ['exit-handler-2']

    def test_task_after_non_exit_handler_group_raises_early(self):
        with pytest.raises(
            ValueError,
            match=r'"\.after\(\)" on task group "condition-[0-9]+" of type dsl\.If is not supported\. Only dsl\.ExitHandler groups can be used as \.after\(\) dependencies\.',
        ):

            @dsl.pipeline(name='pipeline-after-if-group')
            def my_pipeline(flag: str = 'foo'):
                with dsl.If(flag == 'foo') as if_group:
                    print_op(message='Inside condition.')
                print_op(message='After condition.').after(if_group)

    def test_task_after_task_inside_exit_handler_is_lifted(self, tmp_path):
        @dsl.pipeline(name='pipeline-after-task-inside-exit-handler')
        def my_pipeline():
            exit_task = print_op(message='Exit task.')
            with dsl.ExitHandler(exit_task):
                inner_task = print_op(message='Inside exit handler.')
            print_op(message='After exit handler.').after(inner_task)

        depends_on(
            compile_manifest(my_pipeline, tmp_path),
            'print-op-3',
            'exit-handler-1',
        )

    def test_task_after_exit_handler_group_can_use_task_final_status(
        self, tmp_path
    ):
        @dsl.component
        def cancel_handler(status: PipelineTaskFinalStatus):
            print(status)

        @dsl.pipeline(
            name='pipeline-after-exit-handler-group-with-task-final-status'
        )
        def my_pipeline():
            exit_task = print_op(message='Exit task.')
            with dsl.ExitHandler(exit_task) as exit_group:
                print_op(message='Inside exit handler.')
            cancel_handler().after(exit_group).ignore_upstream_failure()

        root = dag_tasks(root_template(compile_manifest(my_pipeline, tmp_path)))
        handler = root['cancel-handler']
        # Failure tolerance: wait for any terminal state of the group.
        assert 'dependencies' not in handler
        for state in ('Succeeded', 'Failed', 'Errored'):
            assert f'exit-handler-1.{state}' in handler['depends']
        status = parameters(handler['arguments'])['status']
        assert 'tasks["exit-handler-1"].status' in status
        assert "'FAILED' : 'SUCCEEDED'" in status

    def test_task_after_exit_handler_group_raises_on_unknown_dependency(
        self, tmp_path
    ):
        @dsl.pipeline(
            name='pipeline-after-exit-handler-group-with-unknown-dependency'
        )
        def my_pipeline():
            downstream = print_op(message='Downstream task.')
            # Cover the compiler validation path that public .after()
            # input validation now prevents.
            downstream._task_spec.dependent_tasks.append('missing-task')

        with pytest.raises(ValueError, match="'missing-task'"):
            compile_manifest(my_pipeline, tmp_path)

    def test_task_after_exit_handler_group_raises_on_ambiguous_name(
        self, tmp_path
    ):
        @dsl.component
        def exit_handler_1():
            pass

        @dsl.pipeline(
            name='pipeline-after-exit-handler-group-with-ambiguous-name'
        )
        def my_pipeline():
            exit_handler_1()
            exit_task = print_op(message='Exit task.')
            with dsl.ExitHandler(exit_task) as exit_group:
                print_op(message='Inside exit handler.')
            print_op(message='After exit handler.').after(exit_group)

        with pytest.raises(ValueError, match='Ambiguous'):
            compile_manifest(my_pipeline, tmp_path)

    def test_root_dag_task_names_are_unique(self, tmp_path):
        # Stock raised the same error for a task that shadows a group name.
        @dsl.component
        def exit_handler_1():
            pass

        @dsl.pipeline
        def my_pipeline():
            exit_handler_1()
            exit_task = print_op(message='Exit task.')
            with dsl.ExitHandler(exit_task):
                print_op(message='Inside exit handler.')

        with pytest.raises(ValueError, match='Ambiguous dependency name'):
            compile_manifest(my_pipeline, tmp_path)

    def test_nested_exit_handlers_compile(self, tmp_path):
        """A31: stock refused nested ExitHandlers ("only ... the outermost
        scope"); native compiles nested exit wrappers, inner exit first."""

        @dsl.pipeline(name='pipeline-with-multiple-exit-handlers')
        def my_pipeline():
            first_exit_task = print_op(message='First exit task.')
            with dsl.ExitHandler(first_exit_task):
                print_op(message='Inside first exit handler.')
                second_exit_task = print_op(message='Second exit task.')
                with dsl.ExitHandler(second_exit_task):
                    print_op(message='Inside second exit handler.')

        manifest = compile_manifest(my_pipeline, tmp_path)
        names = list(templates(manifest))
        for wrapper in ('exit-handler-1-exit', 'exit-handler-2-exit'):
            assert any(wrapper in name for name in names), names


class TestCompileOptionalArtifacts:
    @pytest.mark.parametrize(
        'annotation', [Optional[Input[Artifact]], Optional[Input[Model]]]
    )
    def test_python_comp(self, annotation):
        @dsl.component
        def comp(x: annotation = None):
            print(x)

        assert comp.component_spec.inputs['x'].optional is True
        assert comp.component_spec.inputs['x'].default is None

    def test_python_comp_without_optional_type_modifier(self):
        @dsl.component
        def comp(x: Input[Model] = None):
            print(x)

        assert comp.component_spec.inputs['x'].optional is True

    def test_container_comp(self):
        @dsl.container_component
        def comp(x: Optional[Input[Artifact]] = None):
            return dsl.ContainerSpec(
                image='alpine',
                command=[
                    dsl.IfPresentPlaceholder(
                        input_name='x',
                        then=['echo', x.uri],
                        else_=['echo', 'No artifact provided!'],
                    )
                ],
            )

        assert comp.component_spec.inputs['x'].optional is True

    def test_python_comp_compiles_as_root(self, tmp_path):
        @dsl.component
        def comp(x: Optional[Input[Artifact]] = None):
            print(x)

        compile_manifest(comp, tmp_path)

    @pytest.mark.parametrize(
        'annotation', [Optional[Input[Artifact]], Input[Artifact]]
    )
    def test_pipeline(self, annotation):
        @dsl.pipeline
        def my_pipeline(x: annotation = None):
            print_hello()

        assert my_pipeline.component_spec.inputs['x'].optional is True

    def test_pipeline_compiles_with_optional_artifact_input(self, tmp_path):
        @dsl.pipeline
        def my_pipeline(x: Optional[Input[Artifact]] = None):
            print_hello()

        compile_manifest(my_pipeline, tmp_path)

    def test_pipeline_and_inner_component_together(self):
        @dsl.component
        def comp(x: Optional[Input[Model]] = None):
            print(x)

        @dsl.pipeline
        def my_pipeline(x: Optional[Input[Artifact]] = None):
            comp()

        assert my_pipeline.component_spec.inputs['x'].optional is True
        assert comp.component_spec.inputs['x'].optional is True

    def test_invalid_default_comp(self):
        with pytest.raises(
            ValueError,
            match='Optional Input artifacts may only have default value None',
        ):

            @dsl.component
            def comp(x: Optional[Input[Model]] = 1):
                print(x)

        with pytest.raises(
            ValueError,
            match='Optional Input artifacts may only have default value None',
        ):

            @dsl.component
            def comp2(
                x: Optional[Input[Model]] = Model(name='', uri='', metadata={}),
            ):
                print(x)

    def test_invalid_default_pipeline(self):
        with pytest.raises(
            ValueError,
            match='Optional Input artifacts may only have default value None',
        ):

            @dsl.pipeline
            def my_pipeline(x: Input[Artifact] = 1):
                print_hello()

        with pytest.raises(
            ValueError,
            match='Optional Input artifacts may only have default value None',
        ):

            @dsl.pipeline
            def my_pipeline2(
                x: Input[Artifact] = Artifact(name='', uri='', metadata={}),
            ):
                print_hello()


class TestPythonicArtifactAuthoring:
    ARTIFACT = 'system.Artifact@0.0.1'

    @pytest.mark.parametrize(
        'pythonic,standard,is_list,optional',
        [
            (Artifact, Input[Artifact], False, False),
            (Optional[Artifact], Optional[Input[Artifact]], False, True),
            (List[Artifact], Input[List[Artifact]], True, False),
            (
                Optional[List[Artifact]],
                Optional[Input[List[Artifact]]],
                True,
                True,
            ),
        ],
    )
    def test_pythonic_input_matches_standard_style(
        self, pythonic, standard, is_list, optional
    ):
        def build(annotation):
            if optional:

                @dsl.component
                def comp(in_artifact: annotation = None):
                    print(in_artifact)
            else:

                @dsl.component
                def comp(in_artifact: annotation):
                    print(in_artifact)

            return comp.component_spec.inputs['in_artifact']

        pythonic_spec = build(pythonic)
        assert pythonic_spec.type == self.ARTIFACT
        assert pythonic_spec == build(standard)
        assert pythonic_spec.is_artifact_list is is_list
        assert pythonic_spec.optional is optional

    def test_pythonic_output_artifact(self):
        @dsl.component
        def pythonic_style() -> Artifact:
            return Artifact(uri='gs://my_bucket/foo')

        @dsl.component
        def standard_style(named_output: Output[Artifact]):
            named_output.uri = 'gs://my_bucket/foo'

        assert pythonic_style.component_spec.outputs['Output'].type == (
            self.ARTIFACT
        )
        assert (
            pythonic_style.component_spec.outputs['Output']
            == (standard_style.component_spec.outputs['named_output'])
        )

    def test_pythonic_output_artifact_multiple_returns(self):
        from typing import NamedTuple

        @dsl.component
        def pythonic_style() -> NamedTuple(
            'outputs', a=Artifact, d=dsl.Dataset
        ):
            outputs = NamedTuple('outputs', a=Artifact, d=dsl.Dataset)
            return outputs(
                a=Artifact(uri='gs://my_bucket/foo/artifact'),
                d=Artifact(uri='gs://my_bucket/foo/dataset'),
            )

        @dsl.component
        def standard_style(a: Output[Artifact], d: Output[dsl.Dataset]):
            a.uri = 'gs://my_bucket/foo/artifact'
            d.uri = 'gs://my_bucket/foo/dataset'

        outputs = pythonic_style.component_spec.outputs
        assert outputs['a'].type == self.ARTIFACT
        assert outputs['d'].type == 'system.Dataset@0.0.1'
        assert outputs == standard_style.component_spec.outputs

    def test_pythonic_output_list_artifacts(self):
        with pytest.raises(
            ValueError,
            match=r"Output lists of artifacts are only supported for pipelines\. Got output list of artifacts for output parameter 'Output' of component 'pythonic-style'\.",
        ):

            @dsl.component
            def pythonic_style() -> List[Artifact]:
                pass

    def test_mixed_component_authoring_styles(self, tmp_path):
        @dsl.component
        def back_compat_style(in_artifact: Input[Artifact]) -> Artifact:
            print(in_artifact)
            return Artifact(uri='gs://my_bucket/foo')

        @dsl.component
        def mixed_style(in_artifact: Artifact, out_artifact: Output[Artifact]):
            print(in_artifact)
            out_artifact.uri = 'gs://my_bucket/foo'

        @dsl.component
        def source() -> Artifact:
            return Artifact(uri='gs://my_bucket/source')

        @dsl.pipeline
        def my_pipeline():
            produced = source()
            back_compat_style(in_artifact=produced.output)
            mixed_style(in_artifact=produced.output)

        manifest = compile_manifest(my_pipeline, tmp_path)
        tasks = dag_tasks(root_template(manifest))
        for name in ('back-compat-style', 'mixed-style'):
            artifacts = {
                a['name']: a['from']
                for a in tasks[name]['arguments']['artifacts']
            }
            assert (
                artifacts['in_artifact']
                == '{{tasks.source.outputs.artifacts.Output}}'
            )

    @pytest.mark.parametrize(
        'annotation,is_list,optional',
        [
            (Artifact, False, False),
            (Optional[Artifact], False, True),
            (List[Artifact], True, False),
            (Optional[List[Artifact]], True, True),
        ],
    )
    def test_pipeline_input_artifact(self, annotation, is_list, optional):
        @dsl.component
        def pythonic_style(in_artifact: annotation = None):
            print(in_artifact)

        if optional:

            @dsl.pipeline
            def my_pipeline(in_artifact: annotation = None):
                pythonic_style(in_artifact=in_artifact)
        else:

            @dsl.pipeline
            def my_pipeline(in_artifact: annotation):
                pythonic_style(in_artifact=in_artifact)

        spec = my_pipeline.component_spec.inputs['in_artifact']
        assert spec.type == self.ARTIFACT
        assert spec.is_artifact_list is is_list
        assert spec.optional is optional

    @pytest.mark.parametrize(
        'annotation', [Artifact, Optional[Artifact], List[Artifact]]
    )
    def test_pipeline_input_artifact_compiles(self, tmp_path, annotation):
        @dsl.component
        def pythonic_style(in_artifact: annotation = None):
            print(in_artifact)

        @dsl.pipeline
        def my_pipeline(in_artifact: annotation = None):
            pythonic_style(in_artifact=in_artifact)

        compile_manifest(my_pipeline, tmp_path)

    def test_pipeline_output_artifact(self, tmp_path):
        @dsl.component
        def pythonic_style() -> Artifact:
            return Artifact(uri='gs://my_bucket/foo')

        @dsl.pipeline
        def my_pipeline() -> Artifact:
            return pythonic_style().output

        assert my_pipeline.component_spec.outputs['Output'].type == (
            self.ARTIFACT
        )
        root = root_template(compile_manifest(my_pipeline, tmp_path))
        assert {
            'name': 'Output',
            'from': '{{tasks.pythonic-style.outputs.artifacts.Output}}',
        } in root['outputs']['artifacts']
        assert 'Output' not in parameters(root['outputs'])

    def test_pipeline_output_list_of_artifacts(self, tmp_path):
        @dsl.component
        def noop() -> Artifact:
            return Artifact(uri='gs://my_bucket/foo/bar')

        @dsl.pipeline
        def my_pipeline() -> List[Artifact]:
            with dsl.ParallelFor([1, 2, 3]):
                t = noop()
            return dsl.Collected(t.output)

        spec = my_pipeline.component_spec.outputs['Output']
        assert spec.type == self.ARTIFACT
        assert spec.is_artifact_list is True
        root = root_template(compile_manifest(my_pipeline, tmp_path))
        # Artifact lists travel as URI/metadata parameter pairs.
        assert [p['name'] for p in root['outputs']['parameters']] == [
            'kfp-uri-Output',
            'kfp-meta-Output',
        ]
        assert 'artifacts' not in root['outputs']
        for p in root['outputs']['parameters']:
            assert p['valueFrom']['parameter'].startswith(
                '{{tasks.for-loop-2.outputs.parameters.'
            )

    CONTAINER_MARKER = r"Container Components must wrap input and output artifact annotations with Input/Output type markers \(Input\[<artifact>\] or Output\[<artifact>\]\)\. Got function input 'in_artifact' with annotation "

    def test_container_input_artifact(self):
        with pytest.raises(
            TypeError,
            match=self.CONTAINER_MARKER
            + r"<class 'kfp\.dsl\.types\.artifact_types\.Artifact'>\.",
        ):

            @dsl.container_component
            def comp(in_artifact: Artifact):
                return dsl.ContainerSpec(image='alpine', command=['pwd'])

    def test_container_input_artifact_optional(self):
        with pytest.raises(
            TypeError,
            match=self.CONTAINER_MARKER
            + r"<class 'kfp\.dsl\.types\.artifact_types\.Artifact'>\.",
        ):

            @dsl.container_component
            def comp(in_artifact: Optional[Artifact] = None):
                return dsl.ContainerSpec(image='alpine', command=['pwd'])

    def test_container_input_list_of_artifacts(self):
        with pytest.raises(
            TypeError,
            match=self.CONTAINER_MARKER
            + r'typing\.List\[kfp\.dsl\.types\.artifact_types\.Artifact\]\.',
        ):

            @dsl.container_component
            def comp(in_artifact: List[Artifact]):
                return dsl.ContainerSpec(image='alpine', command=['pwd'])

    def test_container_input_list_of_artifacts_optional(self):
        with pytest.raises(
            TypeError,
            match=self.CONTAINER_MARKER
            + r'typing\.List\[kfp\.dsl\.types\.artifact_types\.Artifact\]\.',
        ):

            @dsl.container_component
            def comp(in_artifact: Optional[List[Artifact]] = None):
                return dsl.ContainerSpec(image='alpine', command=['pwd'])

    @pytest.mark.parametrize('annotation', [Artifact, List[Artifact]])
    def test_container_output_artifact(self, annotation):
        with pytest.raises(
            TypeError,
            match=r'Return annotation should be either ContainerSpec or omitted for container components\.',
        ):

            @dsl.container_component
            def comp() -> annotation:
                return dsl.ContainerSpec(image='alpine', command=['pwd'])


DESCRIPTION = 'pipelines.kubeflow.org/description'
DISPLAY_NAME = 'pipelines.kubeflow.org/display-name'
PARAMETER_TYPES = 'pipelines.kubeflow.org/parameter-types'


class TestYamlComments:
    """Stock prefixed the YAML with a ``# PIPELINE DEFINITION`` comment block.

    The native manifest has no comment header; the same facts live in
    metadata annotations and the root template, which these tests
    assert.
    """

    @pytest.mark.skip(
        reason='No compatibility row: the native compiler emits no '
        '"# PIPELINE DEFINITION" comment header (name, description, inputs '
        'and outputs are metadata annotations and spec fields instead).'
    )
    @pytest.mark.parametrize(
        'stock_test',
        [
            'test_comments_include_inputs_and_outputs_and_pipeline_name',
            'test_no_description',
            'test_description_from_docstring',
            'test_description_from_decorator',
            'test_comments_on_pipeline_with_no_inputs_or_outputs',
            'test_comments_follow_pattern',
            'test_verbose_comment_characteristics',
            'test_comments_on_compiled_components',
            'test_comments_idempotency',
            'test_comment_with_multiline_docstring',
            'test_idempotency_on_comment_with_multiline_docstring',
        ],
    )
    def test_comment_header(self, stock_test):
        raise AssertionError(stock_test)

    def test_name_inputs_and_outputs_are_recorded(self, tmp_path):
        @dsl.pipeline()
        def my_pipeline(
            sample_input1: bool = True, sample_input2: str = 'string'
        ) -> str:
            return my_comp(string=sample_input2, model=sample_input1).output

        manifest = compile_manifest(my_pipeline, tmp_path)
        assert (
            manifest['metadata']['labels']['pipelines.kubeflow.org/pipeline']
            == 'my-pipeline'
        )
        assert manifest['metadata']['annotations'][DISPLAY_NAME] == (
            'my-pipeline'
        )
        assert manifest['spec']['arguments']['parameters'] == [
            {'name': 'sample_input1', 'value': 'true'},
            {'name': 'sample_input2', 'value': 'string'},
        ]
        assert (
            manifest['metadata']['annotations'][PARAMETER_TYPES]
            == '{"sample_input1":"Boolean","sample_input2":"String"}'
        )
        assert root_template(manifest)['outputs']['parameters'] == [
            {
                'name': 'Output',
                'valueFrom': {
                    'parameter': '{{tasks.my-comp.outputs.parameters.Output}}'
                },
            }
        ]

    def test_no_description(self, tmp_path):
        @dsl.pipeline()
        def pipeline_with_no_description(
            sample_input1: bool = True, sample_input2: str = 'string'
        ) -> str:
            return my_comp(string=sample_input2, model=sample_input1).output

        manifest = compile_manifest(pipeline_with_no_description, tmp_path)
        assert manifest['metadata']['annotations'][DESCRIPTION] == ''

    def test_description_from_docstring(self, tmp_path):
        @dsl.pipeline()
        def pipeline_with_description(
            sample_input1: bool = True, sample_input2: str = 'string'
        ) -> str:
            """This is a description of this pipeline."""
            return my_comp(string=sample_input2, model=sample_input1).output

        manifest = compile_manifest(pipeline_with_description, tmp_path)
        assert (
            manifest['metadata']['annotations'][DESCRIPTION]
            == 'This is a description of this pipeline.'
        )

    def test_description_from_decorator(self, tmp_path):
        @dsl.pipeline(description='Prefer this description.')
        def pipeline_with_description(
            sample_input1: bool = True, sample_input2: str = 'string'
        ) -> str:
            """Don't prefer this description."""
            return my_comp(string=sample_input2, model=sample_input1).output

        manifest = compile_manifest(pipeline_with_description, tmp_path)
        assert (
            manifest['metadata']['annotations'][DESCRIPTION]
            == 'Prefer this description.'
        )

    def test_pipeline_with_no_inputs_or_outputs(self, tmp_path):
        @dsl.pipeline()
        def pipeline_with_no_inputs() -> str:
            return my_comp(string='string', model=True).output

        manifest = compile_manifest(pipeline_with_no_inputs, tmp_path)
        assert manifest['spec']['arguments'] == {'parameters': []}
        assert manifest['metadata']['annotations'][PARAMETER_TYPES] == '{}'

        @dsl.pipeline()
        def pipeline_with_no_outputs(
            sample_input1: bool = True, sample_input2: str = 'string'
        ):
            my_comp(string=sample_input2, model=sample_input1)

        manifest = compile_manifest(pipeline_with_no_outputs, tmp_path)
        assert 'outputs' not in root_template(manifest)

    def test_description_on_compiled_components(self, tmp_path):
        # Docstrings are assigned so docformatter cannot rewrite the fixture.
        def my_component(string: str, model: bool) -> str:
            return string

        my_component.__doc__ = 'component description.'
        manifest = compile_manifest(dsl.component(my_component), tmp_path)
        annotations = manifest['metadata']['annotations']
        assert annotations[DISPLAY_NAME] == 'my-component'
        assert annotations[DESCRIPTION] == 'component description.'
        assert json.loads(annotations[PARAMETER_TYPES]) == {
            'string': 'String',
            'model': 'Boolean',
        }

        def my_container_component(text: str, output_path: dsl.OutputPath(str)):
            return dsl.ContainerSpec(
                image='python:3.11',
                command=['my_program', text],
                args=['--output_path', output_path],
            )

        my_container_component.__doc__ = 'component description.'
        manifest = compile_manifest(
            dsl.container_component(my_container_component), tmp_path
        )
        annotations = manifest['metadata']['annotations']
        assert annotations[DISPLAY_NAME] == 'my-container-component'
        assert annotations[DESCRIPTION] == 'component description.'
        assert annotations[PARAMETER_TYPES] == '{"text":"String"}'

    def test_multiline_docstring_description(self, tmp_path):
        def pipeline_with_multiline_definition(
            sample_input1: bool = True, sample_input2: str = 'string'
        ) -> str:
            return my_comp(string=sample_input2, model=sample_input1).output

        # Stock's fixture docstring, assigned so docformatter leaves it alone.
        pipeline_with_multiline_definition.__doc__ = (
            'docstring short description.\n'
            '            docstring long description. docstring long description.\n'
            '            '
        )
        manifest = compile_manifest(
            dsl.pipeline()(pipeline_with_multiline_definition), tmp_path
        )
        assert manifest['metadata']['annotations'][DESCRIPTION] == (
            'docstring short description.\n'
            'docstring long description. docstring long description.'
        )

    @pytest.mark.xfail(
        strict=True,
        reason='C44: a compiled pipeline is a WorkflowTemplate that '
        'load_component_from_file rejects, so the stock reload-and-recompile '
        'idempotency check cannot run.',
    )
    def test_compiled_pipeline_reloads_as_component(self, tmp_path):
        @dsl.pipeline()
        def my_pipeline(
            sample_input1: bool = True, sample_input2: str = 'string'
        ) -> str:
            """My description."""
            return my_comp(string=sample_input2, model=sample_input1).output

        path = tmp_path / 'pipeline.yaml'
        compiler.Compiler().compile(my_pipeline, str(path))
        loaded = components.load_component_from_file(str(path))
        assert loaded.description == 'My description.'


class TestRootArtifactInputs:
    """L02: optional root artifact inputs are absent at run time, as stock's
    run API could not supply them; required ones are refused up front."""

    def test_optional_root_artifact_is_absent_for_optional_consumers(
        self, tmp_path
    ):
        @dsl.component
        def describe(model: Optional[Input[Artifact]] = None) -> str:
            return 'absent' if model is None else model.uri

        @dsl.pipeline
        def my_pipeline(model: Optional[Input[Artifact]] = None):
            describe(model=model)

        manifest = compile_manifest(my_pipeline, tmp_path)
        root = root_template(manifest)
        assert 'artifacts' not in root.get('inputs', {})
        assert 'artifacts' not in manifest['spec']['arguments']
        assert 'arguments' not in dag_tasks(root)['describe'] or not dag_tasks(
            root
        )['describe']['arguments'].get('artifacts')
        # The consumer tolerates the omission: empty URI/metadata defaults and
        # an optional artifact input, which the runtime turns into None.
        describe = templates(manifest)[dag_tasks(root)['describe']['template']]
        parameters = {p['name']: p for p in describe['inputs']['parameters']}
        assert parameters['kfp-uri-model']['default'] == ''
        assert parameters['kfp-meta-model']['default'] == ''
        artifacts = {a['name']: a for a in describe['inputs']['artifacts']}
        assert artifacts['model']['optional'] is True

    def test_required_root_artifact_is_refused(self, tmp_path):
        @dsl.component
        def describe(model: Input[Artifact]) -> str:
            return model.uri

        @dsl.pipeline
        def my_pipeline(model: Input[Artifact]):
            describe(model=model)

        with pytest.raises(ValueError, match='Root artifact input'):
            compile_manifest(my_pipeline, tmp_path)

    def test_optional_root_artifact_cannot_feed_a_required_consumer(
        self, tmp_path
    ):
        @dsl.component
        def describe(model: Input[Artifact]) -> str:
            return model.uri

        @dsl.pipeline
        def my_pipeline(model: Optional[Input[Artifact]] = None):
            describe(model=model)

        with pytest.raises(ValueError, match='has no artifact at run time'):
            compile_manifest(my_pipeline, tmp_path)
