# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Control-flow compilation ported from stock's ``compiler_test.py``.

Stock asserted CEL trigger policies in the IR; natively a condition is an
Argo ``when`` expression on the branch's DAG task, and loop item fields
are projected in the loop's fan-out wrapper. Authoring-time errors are
asserted unchanged. Divergences are strict xfails naming the gap.
"""

import json
import re

import pytest
import yaml

from kfp import compiler, dsl
from kfp.dsl import tasks_group

CHANNEL = r'ch-[0-9a-f]{16}'


@dsl.component
def flip_coin() -> str:
    import random

    return 'heads' if random.randint(0, 1) == 0 else 'tails'


@dsl.component
def print_and_return(text: str) -> str:
    print(text)
    return text


@dsl.component
def roll_three_sided_die() -> str:
    import random

    return ['heads', 'tails', 'draw'][random.randint(0, 2)]


@dsl.component
def int_zero_through_three() -> int:
    import random

    return random.randint(0, 3)


@dsl.component
def return_1() -> int:
    return 1


@dsl.component
def return_float() -> float:
    return 1.0


@dsl.component
def return_bool() -> bool:
    return True


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


def dag_templates(manifest):
    return [t for t in manifest['spec']['templates'] if 'dag' in t]


def template_with_task(manifest, task_name):
    return next(t for t in dag_templates(manifest) if task_name in dag_tasks(t))


def parameters(section):
    return {
        p['name']: p.get('value', p.get('default'))
        for p in (section or {}).get('parameters', [])
    }


def input_names(template):
    return [p['name'] for p in template.get('inputs', {}).get('parameters', [])]


def whens(manifest):
    """Group names are unique across the pipeline, so index by task name."""
    return {
        task['name']: task['when']
        for t in dag_templates(manifest)
        for task in t['dag']['tasks']
        if 'when' in task
    }


def task_output(task_name, output='Output'):
    return f'tasks["{task_name}"].outputs.parameters["{output}"]'


def forwarded(when):
    """The branch input a condition compares inside an if/elif/else wrapper."""
    (name,) = set(
        re.findall(r'inputs\.parameters\["(' + CHANNEL + r')"\]', when)
    )
    return f'inputs.parameters["{name}"]'


class TestConditionLogic:
    def test_if(self, tmp_path):
        @dsl.pipeline
        def flip_coin_pipeline():
            flip_coin_task = flip_coin()
            with dsl.If(flip_coin_task.output == 'heads'):
                print_and_return(text='Got heads!')

        assert whens(compile_manifest(flip_coin_pipeline, tmp_path)) == {
            'condition-1': '{{=(' + task_output('flip-coin') + ' == "heads")}}'
        }

    def test_if_else(self, tmp_path):
        @dsl.pipeline
        def flip_coin_pipeline():
            flip_coin_task = flip_coin()
            with dsl.If(flip_coin_task.output == 'heads'):
                print_and_return(text='Got heads!')
            with dsl.Else():
                print_and_return(text='Got tails!')

        manifest = compile_manifest(flip_coin_pipeline, tmp_path)
        conditions = whens(manifest)
        assert set(conditions) == {'condition-2', 'condition-3'}
        value = forwarded(conditions['condition-2'])
        assert conditions['condition-2'] == f'{{{{=({value} == "heads")}}}}'
        assert conditions['condition-3'] == f'{{{{=!({value} == "heads")}}}}'
        # Both branches live in one wrapper fed by the coin flip.
        wrapper = template_with_task(manifest, 'condition-2')
        assert set(dag_tasks(wrapper)) == {'condition-2', 'condition-3'}
        root = dag_tasks(root_template(manifest))
        assert parameters(root['condition-branches-1']['arguments']) == {
            value[len('inputs.parameters["') : -2]: '{{'
            + 'tasks.flip-coin.outputs.parameters.Output}}'
        }

    def test_if_elif_else(self, tmp_path):
        @dsl.pipeline
        def flip_coin_pipeline():
            flip_coin_task = roll_three_sided_die()
            with dsl.If(flip_coin_task.output == 'heads'):
                print_and_return(text='Got heads!')
            with dsl.Elif(flip_coin_task.output == 'tails'):
                print_and_return(text='Got tails!')
            with dsl.Else():
                print_and_return(text='Draw!')

        conditions = whens(compile_manifest(flip_coin_pipeline, tmp_path))
        v = forwarded(conditions['condition-2'])
        assert conditions == {
            'condition-2': f'{{{{=({v} == "heads")}}}}',
            'condition-3': f'{{{{=!({v} == "heads") && ({v} == "tails")}}}}',
            'condition-4': f'{{{{=!({v} == "heads") && !({v} == "tails")}}}}',
        }

    def test_if_multiple_elif_else(self, tmp_path):
        @dsl.pipeline
        def int_to_string():
            int_task = int_zero_through_three()
            with dsl.If(int_task.output == 0):
                print_and_return(text='Got zero!')
            with dsl.Elif(int_task.output == 1):
                print_and_return(text='Got one!')
            with dsl.Elif(int_task.output == 2):
                print_and_return(text='Got two!')
            with dsl.Else():
                print_and_return(text='Got three!')

        conditions = whens(compile_manifest(int_to_string, tmp_path))
        v = 'fromJSON(' + forwarded(conditions['condition-2']) + ')'
        assert conditions == {
            'condition-2': f'{{{{=({v} == 0)}}}}',
            'condition-3': f'{{{{=!({v} == 0) && ({v} == 1)}}}}',
            'condition-4': f'{{{{=!({v} == 0) && !({v} == 1) && ({v} == 2)}}}}',
            'condition-5': f'{{{{=!({v} == 0) && !({v} == 1) && !({v} == 2)}}}}',
        }

    def test_nested_if_elif_else_with_pipeline_param(self, tmp_path):
        @dsl.pipeline
        def flip_coin_pipeline(confirm: bool):
            int_task = int_zero_through_three()
            heads_task = flip_coin()

            with dsl.If(heads_task.output == 'heads'):
                with dsl.If(int_task.output == 0):
                    print_and_return(text='Got zero!')

                with dsl.Elif(int_task.output == 1):
                    print_and_return(text='Got one!')
                    with dsl.If(confirm == True):  # noqa: E712
                        print_and_return(text='Confirmed: definitely got one.')

                with dsl.Elif(int_task.output == 2):
                    print_and_return(text='Got two!')

                with dsl.Else():
                    print_and_return(text='Got three!')

                # the wrapper must work with multiple if/elif/else groups
                with dsl.ParallelFor(['Game #1', 'Game #2']) as game_no:
                    heads_task = flip_coin()
                    with dsl.If(heads_task.output == 'heads'):
                        print_and_return(text=game_no)
                        print_and_return(text='Got heads!')
                    with dsl.Else():
                        print_and_return(text=game_no)
                        print_and_return(text='Got tail!')

        manifest = compile_manifest(flip_coin_pipeline, tmp_path)
        conditions = whens(manifest)
        # top level
        assert conditions['condition-1'] == (
            '{{=(' + task_output('flip-coin') + ' == "heads")}}'
        )
        # second level: if / elif / elif / else over the integer
        v = 'fromJSON(' + forwarded(conditions['condition-3']) + ')'
        assert conditions['condition-3'] == f'{{{{=({v} == 0)}}}}'
        assert conditions['condition-4'] == (
            f'{{{{=!({v} == 0) && ({v} == 1)}}}}'
        )
        assert conditions['condition-6'] == (
            f'{{{{=!({v} == 0) && !({v} == 1) && ({v} == 2)}}}}'
        )
        assert conditions['condition-7'] == (
            f'{{{{=!({v} == 0) && !({v} == 1) && !({v} == 2)}}}}'
        )
        # third level: the pipeline parameter reaches the nested condition
        confirm = 'fromJSON(' + forwarded(conditions['condition-5']) + ')'
        assert conditions['condition-5'] == f'{{{{=({confirm} == true)}}}}'
        wrapper = template_with_task(manifest, 'condition-5')
        assert set(dag_tasks(wrapper)) == {'print-and-return-2', 'condition-5'}
        # second group inside the loop, keyed on the loop's own coin flip
        coin = forwarded(conditions['condition-11'])
        assert conditions['condition-11'] == f'{{{{=({coin} == "heads")}}}}'
        assert conditions['condition-12'] == f'{{{{=!({coin} == "heads")}}}}'
        loop_body = template_with_task(manifest, 'condition-branches-10')
        branches = dag_tasks(loop_body)['condition-branches-10']
        assert (
            parameters(branches['arguments'])[
                coin[len('inputs.parameters["') : -2]
            ]
            == '{{tasks.flip-coin-2.outputs.parameters.Output}}'
        )

    def test_multiple_ifs_permitted(self, tmp_path):
        @dsl.pipeline
        def flip_coin_pipeline():
            flip_coin_task = flip_coin()
            with dsl.If(flip_coin_task.output == 'heads'):
                print_and_return(text='Got heads!')
            with dsl.If(flip_coin_task.output == 'tails'):
                print_and_return(text='Got tails!')

        assert whens(compile_manifest(flip_coin_pipeline, tmp_path)) == {
            'condition-1': '{{=(' + task_output('flip-coin') + ' == "heads")}}',
            'condition-2': '{{=(' + task_output('flip-coin') + ' == "tails")}}',
        }

    def test_multiple_else_not_permitted(self):
        with pytest.raises(
            tasks_group.InvalidControlFlowException,
            match=r'Cannot use dsl\.Else following another dsl\.Else\. dsl\.Else can only be used following an upstream dsl\.If or dsl\.Elif\.',
        ):

            @dsl.pipeline
            def flip_coin_pipeline():
                flip_coin_task = flip_coin()
                with dsl.If(flip_coin_task.output == 'heads'):
                    print_and_return(text='Got heads!')
                with dsl.Else():
                    print_and_return(text='Got tails!')
                with dsl.Else():
                    print_and_return(text='Got tails!')

    def test_else_no_if_not_supported(self):
        with pytest.raises(
            tasks_group.InvalidControlFlowException,
            match=r'dsl\.Else can only be used following an upstream dsl\.If or dsl\.Elif\.',
        ):

            @dsl.pipeline
            def flip_coin_pipeline():
                with dsl.Else():
                    print_and_return(text='Got unknown')

    def test_elif_no_if_not_supported(self):
        with pytest.raises(
            tasks_group.InvalidControlFlowException,
            match=r'dsl\.Elif can only be used following an upstream dsl\.If or dsl\.Elif\.',
        ):

            @dsl.pipeline
            def flip_coin_pipeline():
                flip_coin_task = flip_coin()
                with dsl.Elif(flip_coin_task.output == 'heads'):
                    print_and_return(text='Got heads!')

    def test_boolean_condition_has_helpful_error(self):
        with pytest.raises(
            ValueError,
            match=r'Got constant boolean True as a condition\. This is likely because the provided condition evaluated immediately\. At least one of the operands must be an output from an upstream task or a pipeline parameter\.',
        ):

            @dsl.pipeline
            def my_pipeline():
                with dsl.Condition('foo' == 'foo'):  # noqa: PLR0133
                    print_and_return(text='I will always run.')

    def test_boolean_elif_has_helpful_error(self):
        with pytest.raises(
            ValueError,
            match=r'Got constant boolean False as a condition\. This is likely because the provided condition evaluated immediately\. At least one of the operands must be an output from an upstream task or a pipeline parameter\.',
        ):

            @dsl.pipeline
            def my_pipeline(text: str):
                with dsl.If(text == 'foo'):
                    print_and_return(text='I will always run.')
                with dsl.Elif('foo' == 'bar'):  # noqa: PLR0133
                    print_and_return(text='I will never run.')

    def test_tasks_instantiated_between_if_else_and_elif_permitted(
        self, tmp_path
    ):
        @dsl.pipeline
        def flip_coin_pipeline():
            flip_coin_task = flip_coin()
            with dsl.If(flip_coin_task.output == 'heads'):
                print_and_return(text='Got heads on coin one!')

            flip_coin_task_2 = flip_coin()

            with dsl.Elif(flip_coin_task_2.output == 'tails'):
                print_and_return(text='Got heads on coin two!')

            flip_coin_task_3 = flip_coin()

            with dsl.Else():
                print_and_return(
                    text=f'Coin three result: {flip_coin_task_3.output}'
                )

        manifest = compile_manifest(flip_coin_pipeline, tmp_path)
        conditions = whens(manifest)
        root = dag_tasks(root_template(manifest))
        forwarded_inputs = parameters(root['condition-branches-1']['arguments'])
        by_source = {
            v: f'inputs.parameters["{k}"]' for k, v in forwarded_inputs.items()
        }
        one = by_source['{{tasks.flip-coin.outputs.parameters.Output}}']
        two = by_source['{{tasks.flip-coin-2.outputs.parameters.Output}}']
        assert conditions == {
            'condition-2': f'{{{{=({one} == "heads")}}}}',
            'condition-3': f'{{{{=!({one} == "heads") && ({two} == "tails")}}}}',
            'condition-4': f'{{{{=!({one} == "heads") && !({two} == "tails")}}}}',
        }
        assert sorted(root['condition-branches-1']['dependencies']) == [
            'flip-coin',
            'flip-coin-2',
        ]
        # The third coin is consumed only by the else branch, so it runs
        # inside the wrapper and only that branch waits for it.
        wrapper = dag_tasks(template_with_task(manifest, 'condition-4'))
        assert 'flip-coin-3' in wrapper
        assert wrapper['condition-4']['dependencies'] == ['flip-coin-3']

    def test_other_control_flow_instantiated_between_if_else_not_permitted(
        self,
    ):
        with pytest.raises(
            tasks_group.InvalidControlFlowException,
            match=r'dsl\.Else can only be used following an upstream dsl\.If or dsl\.Elif\.',
        ):

            @dsl.pipeline
            def flip_coin_pipeline():
                flip_coin_task = flip_coin()
                with dsl.If(flip_coin_task.output == 'heads'):
                    print_and_return(text='Got heads!')
                with dsl.ParallelFor(['foo', 'bar']) as item:
                    print_and_return(text=item)
                with dsl.Else():
                    print_and_return(text='Got tails!')

    @staticmethod
    def _compile_condition(tmp_path, condition_fn, condition_cls=dsl.If):
        @dsl.pipeline
        def my_pipeline():
            tasks = {
                'int': return_1(),
                'int2': return_1(),
                'float': return_float(),
                'float2': return_float(),
                'bool': return_bool(),
                'str': flip_coin(),
            }
            if condition_cls is dsl.Elif:
                with dsl.If(tasks['int'].output == 0):
                    print_and_return(text='body-1')
                with dsl.Elif(condition_fn(tasks)):
                    print_and_return(text='body-2')
            else:
                with condition_cls(condition_fn(tasks)):
                    print_and_return(text='body')

        conditions = whens(compile_manifest(my_pipeline, tmp_path))
        if condition_cls is dsl.Elif:
            # The Elif lives in a nested template that receives the channel
            # as an input parameter; compare against the task output form.
            return re.sub(
                r'inputs\.parameters\["ch-[0-9a-f]+"\]',
                task_output('return-1').replace('\\', '\\\\'),
                conditions['condition-3'],
            )
        return conditions['condition-1']

    INT = 'fromJSON(' + task_output('return-1') + ')'
    INT2 = 'fromJSON(' + task_output('return-1-2') + ')'
    FLOAT = 'fromJSON(' + task_output('return-float') + ')'
    FLOAT2 = 'fromJSON(' + task_output('return-float-2') + ')'
    BOOL = 'fromJSON(' + task_output('return-bool') + ')'
    STR = task_output('flip-coin')

    @pytest.mark.parametrize(
        'condition_fn,condition_cls,expected',
        [
            pytest.param(
                lambda t: t['int'].output == True,  # noqa: E712
                dsl.If,
                f'{{{{=(({INT} != 0) == true)}}}}',
                id='int_chan_equals_true',
            ),
            pytest.param(
                lambda t: True == t['int'].output,  # noqa: E712
                dsl.If,
                f'{{{{=(({INT} != 0) == true)}}}}',
                id='true_equals_int_chan_reflected',
            ),
            pytest.param(
                lambda t: t['int'].output != True,  # noqa: E712
                dsl.If,
                f'{{{{=(({INT} != 0) != true)}}}}',
                id='int_chan_not_equals_true',
            ),
            pytest.param(
                lambda t: t['int'].output == False,  # noqa: E712
                dsl.If,
                f'{{{{=(({INT} != 0) == false)}}}}',
                id='int_chan_equals_false',
            ),
            pytest.param(
                lambda t: t['float'].output == True,  # noqa: E712
                dsl.If,
                f'{{{{=(({FLOAT} != 0.0) == true)}}}}',
                id='float_chan_equals_true',
            ),
            pytest.param(
                lambda t: t['float'].output == False,  # noqa: E712
                dsl.If,
                f'{{{{=(({FLOAT} != 0.0) == false)}}}}',
                id='float_chan_equals_false',
            ),
            pytest.param(
                lambda t: t['float'].output != True,  # noqa: E712
                dsl.If,
                f'{{{{=(({FLOAT} != 0.0) != true)}}}}',
                id='float_chan_not_equals_true',
            ),
            pytest.param(
                lambda t: t['int'].output == True,  # noqa: E712
                dsl.Condition,
                f'{{{{=(({INT} != 0) == true)}}}}',
                id='condition_alias_int_chan_equals_true',
            ),
            pytest.param(
                lambda t: t['int'].output == True,  # noqa: E712
                dsl.Elif,
                f'{{{{=!({INT} == 0) && (({INT} != 0) == true)}}}}',
                id='elif_int_chan_equals_true',
            ),
            pytest.param(
                lambda t: t['int'].output == t['bool'].output,
                dsl.If,
                f'{{{{=(({INT} != 0) == {BOOL})}}}}',
                id='int_chan_equals_bool_chan',
            ),
            pytest.param(
                lambda t: t['bool'].output == 1,
                dsl.If,
                f'{{{{=({BOOL} == true)}}}}',
                id='bool_chan_equals_one',
            ),
            pytest.param(
                lambda t: t['bool'].output == 0,
                dsl.If,
                f'{{{{=({BOOL} == false)}}}}',
                id='bool_chan_equals_zero',
            ),
            pytest.param(
                lambda t: t['bool'].output == 1.5,
                dsl.If,
                f'{{{{=({BOOL} == true)}}}}',
                id='bool_chan_equals_float_literal',
            ),
            pytest.param(
                lambda t: 1 == t['bool'].output,
                dsl.If,
                f'{{{{=({BOOL} == true)}}}}',
                id='one_equals_bool_chan_reflected',
            ),
            pytest.param(
                lambda t: t['str'].output == True,  # noqa: E712
                dsl.If,
                f'{{{{=({STR} == "true")}}}}',
                id='str_chan_equals_true',
            ),
        ],
    )
    def test_numeric_bool_condition_bug_cases(
        self, tmp_path, condition_fn, condition_cls, expected
    ):
        assert (
            self._compile_condition(tmp_path, condition_fn, condition_cls)
            == expected
        )

    @pytest.mark.parametrize(
        'condition_fn,expected',
        [
            pytest.param(
                lambda t: t['bool'].output == True,  # noqa: E712
                f'{{{{=({BOOL} == true)}}}}',
                id='bool_chan_equals_true',
            ),
            pytest.param(
                lambda t: t['bool'].output == False,  # noqa: E712
                f'{{{{=({BOOL} == false)}}}}',
                id='bool_chan_equals_false',
            ),
            pytest.param(
                lambda t: t['int'].output == 1,
                f'{{{{=({INT} == 1)}}}}',
                id='int_chan_equals_one',
            ),
            pytest.param(
                lambda t: t['int'].output == t['int2'].output,
                f'{{{{=({INT} == {INT2})}}}}',
                id='int_chan_equals_int_chan',
            ),
            pytest.param(
                lambda t: t['float'].output == t['float2'].output,
                f'{{{{=({FLOAT} == {FLOAT2})}}}}',
                id='float_chan_equals_float_chan',
            ),
            pytest.param(
                lambda t: t['float'].output == 1.5,
                f'{{{{=({FLOAT} == 1.5)}}}}',
                id='float_chan_equals_literal',
            ),
            pytest.param(
                lambda t: t['int'].output == 1.5,
                f'{{{{=({INT} == 1.5)}}}}',
                id='int_chan_equals_float_literal',
            ),
        ],
    )
    def test_condition_guard_cases(self, tmp_path, condition_fn, expected):
        assert self._compile_condition(tmp_path, condition_fn) == expected


class TestConditionStringLiteral:
    @pytest.mark.parametrize(
        'literal',
        ['heads', "it's", 'C:\\temp', "\\'", 'line1\nline2', 'line1\r\nline2'],
    )
    def test_string_literal_is_escaped(self, tmp_path, literal):
        @dsl.pipeline
        def flip_coin_pipeline():
            flip_coin_task = flip_coin()
            with dsl.If(flip_coin_task.output == literal):
                print_and_return(text='Matched!')

        when = whens(compile_manifest(flip_coin_pipeline, tmp_path))[
            'condition-1'
        ]
        # The literal is a JSON string, which expr reads back verbatim.
        assert when == (
            '{{=('
            + task_output('flip-coin')
            + ' == '
            + json.dumps(literal)
            + ')}}'
        )
        assert yaml.safe_load(yaml.dump({'when': when}))['when'] == when


ITEMS = [
    {'who': 'alice', 'greeting': 'hello alice'},
    {'who': 'bob', 'greeting': 'hello bob'},
]


def fanout_template(manifest, body_template_name):
    """The ``withParam`` wrapper that iterates ``body_template_name``."""
    return next(
        t
        for t in dag_templates(manifest)
        if any(
            task.get('withParam') and task['template'] == body_template_name
            for task in t['dag']['tasks']
        )
    )


def projected_field(fanout, channel):
    """The item field a fan-out wrapper projects into ``channel``."""
    value = parameters(dag_tasks(fanout)['iteration']['arguments'])[channel]
    assert value.startswith('{{=') and 'item' in value, value
    fields = set(re.findall(r'\["([a-z_]+)"\]', value))
    assert len(fields) == 1, value
    return fields.pop()


def channel_of(reference):
    match = re.fullmatch(
        r'\{\{inputs\.parameters\.(' + CHANNEL + r')\}\}', reference
    )
    assert match, reference
    return match[1]


@dsl.component
def show(msg: str) -> str:
    return msg


class TestParallelForDictItemScoping:
    """Fields of dict loop items used below other groups (stock #13273)."""

    def test_field_used_inside_condition_in_loop(self, tmp_path):
        @dsl.pipeline
        def my_pipeline(should_run: bool = True):
            with dsl.ParallelFor(items=ITEMS) as item:
                with dsl.If(should_run == True):  # noqa: E712
                    show(msg=item.greeting)

        manifest = compile_manifest(my_pipeline, tmp_path)
        condition = template_with_task(manifest, 'show')
        channel = channel_of(
            parameters(dag_tasks(condition)['show']['arguments'])['msg']
        )
        assert channel in input_names(condition)
        # The loop body passes the projected field on to the condition.
        loop = template_with_task(manifest, 'condition-3')
        assert channel in input_names(loop)
        assert (
            parameters(dag_tasks(loop)['condition-3']['arguments'])[channel]
            == '{{inputs.parameters.' + channel + '}}'
        )
        # The fan-out wrapper is where the field is read from the item.
        fanout = fanout_template(manifest, loop['name'])
        assert projected_field(fanout, channel) == 'greeting'

    def test_field_used_inside_nested_conditions_in_loop(self, tmp_path):
        @dsl.pipeline
        def my_pipeline(a: bool = True, b: bool = True):
            with dsl.ParallelFor(items=ITEMS) as item:
                with dsl.If(a == True):  # noqa: E712
                    with dsl.If(b == True):  # noqa: E712
                        show(msg=item.greeting)

        manifest = compile_manifest(my_pipeline, tmp_path)
        inner = template_with_task(manifest, 'show')
        channel = channel_of(
            parameters(dag_tasks(inner)['show']['arguments'])['msg']
        )
        outer = template_with_task(manifest, 'condition-4')
        assert outer is not inner
        for template in (inner, outer):
            assert channel in input_names(template)
        assert (
            parameters(dag_tasks(outer)['condition-4']['arguments'])[channel]
            == '{{inputs.parameters.' + channel + '}}'
        )
        loop = template_with_task(manifest, 'condition-3')
        assert projected_field(
            fanout_template(manifest, loop['name']), channel
        ) == ('greeting')

    def test_condition_on_field_in_loop(self, tmp_path):
        @dsl.pipeline
        def my_pipeline():
            with dsl.ParallelFor(items=ITEMS) as item:
                with dsl.If(item.who == 'alice'):
                    show(msg=item.greeting)

        manifest = compile_manifest(my_pipeline, tmp_path)
        loop = template_with_task(manifest, 'condition-3')
        when = dag_tasks(loop)['condition-3']['when']
        who = forwarded(when)
        assert when == f'{{{{=({who} == "alice")}}}}'
        fanout = fanout_template(manifest, loop['name'])
        assert projected_field(
            fanout, who[len('inputs.parameters["') : -2]
        ) == ('who')
        condition = template_with_task(manifest, 'show')
        greeting = channel_of(
            parameters(dag_tasks(condition)['show']['arguments'])['msg']
        )
        assert projected_field(fanout, greeting) == 'greeting'

    def test_field_does_not_leak_above_its_loop(self, tmp_path):
        @dsl.component
        def on_exit():
            pass

        @dsl.pipeline
        def my_pipeline():
            exit_task = on_exit()
            with dsl.ExitHandler(exit_task):
                with dsl.ParallelFor(items=ITEMS) as item:
                    show(msg=item.greeting)

        manifest = compile_manifest(my_pipeline, tmp_path)
        root = dag_tasks(root_template(manifest))
        assert root['exit-handler-1'].get('arguments', {}) == {}
        wrapper = templates(manifest)[root['exit-handler-1']['template']]
        body = templates(manifest)[dag_tasks(wrapper)['body']['template']]
        for template in (wrapper, body):
            assert input_names(template) == []
        loop = template_with_task(manifest, 'show')
        channel = channel_of(
            parameters(dag_tasks(loop)['show']['arguments'])['msg']
        )
        assert projected_field(
            fanout_template(manifest, loop['name']), channel
        ) == ('greeting')

    def test_outer_loop_field_used_in_inner_loop(self, tmp_path):
        @dsl.component
        def show2(msg: str, n: int) -> str:
            return f'{msg} {n}'

        @dsl.pipeline
        def my_pipeline():
            with dsl.ParallelFor(items=ITEMS) as item:
                with dsl.ParallelFor(items=[1, 2]) as number:
                    show2(msg=item.greeting, n=number)

        manifest = compile_manifest(my_pipeline, tmp_path)
        inner = template_with_task(manifest, 'show2')
        arguments = parameters(dag_tasks(inner)['show2']['arguments'])
        greeting = channel_of(arguments['msg'])
        number = channel_of(arguments['n'])
        assert greeting in input_names(inner)
        inner_fanout = fanout_template(manifest, inner['name'])
        iteration = parameters(
            dag_tasks(inner_fanout)['iteration']['arguments']
        )
        assert iteration[number] == '{{item}}'
        assert iteration[greeting] == '{{inputs.parameters.' + greeting + '}}'
        outer = template_with_task(manifest, 'for-loop-4')
        assert greeting in input_names(outer)
        assert (
            parameters(dag_tasks(outer)['for-loop-4']['arguments'])[greeting]
            == '{{inputs.parameters.' + greeting + '}}'
        )
        assert (
            projected_field(fanout_template(manifest, outer['name']), greeting)
            == 'greeting'
        )


class TestBooleanInputCompiledCorrectly:
    """Defaults of True guard against a falsy-default serialization bug."""

    @staticmethod
    def container_templates(manifest):
        return [t for t in manifest['spec']['templates'] if 'container' in t]

    def test_python_component(self, tmp_path):
        @dsl.component
        def comp(boolean: bool = True) -> bool:
            return boolean

        manifest = compile_manifest(comp, tmp_path)
        assert manifest['spec']['arguments']['parameters'] == [
            {'name': 'boolean', 'value': 'true'}
        ]
        (container,) = self.container_templates(manifest)
        assert container['inputs']['parameters'] == [
            {'name': 'boolean', 'default': 'true'}
        ]
        assert (
            manifest['metadata']['annotations'][
                'pipelines.kubeflow.org/parameter-types'
            ]
            == '{"boolean":"Boolean"}'
        )

    def test_python_component_with_overrides(self, tmp_path):
        @dsl.component
        def comp(boolean: bool = False) -> bool:
            return boolean

        manifest = compile_manifest(
            comp, tmp_path, pipeline_parameters={'boolean': True}
        )
        assert manifest['spec']['arguments']['parameters'] == [
            {'name': 'boolean', 'value': 'true'}
        ]

    def test_container_component(self, tmp_path):
        @dsl.container_component
        def comp(boolean: bool = True):
            return dsl.ContainerSpec(image='alpine', command=['echo', boolean])

        manifest = compile_manifest(comp, tmp_path)
        assert manifest['spec']['arguments']['parameters'] == [
            {'name': 'boolean', 'value': 'true'}
        ]
        (container,) = self.container_templates(manifest)
        assert container['inputs']['parameters'] == [
            {'name': 'boolean', 'default': 'true'}
        ]
        assert container['container']['command'] == [
            'echo',
            '{{inputs.parameters.boolean}}',
        ]

    def test_container_component_with_overrides(self, tmp_path):
        @dsl.container_component
        def comp(boolean: bool = True):
            return dsl.ContainerSpec(image='alpine', command=['echo', boolean])

        manifest = compile_manifest(
            comp, tmp_path, pipeline_parameters={'boolean': True}
        )
        assert manifest['spec']['arguments']['parameters'] == [
            {'name': 'boolean', 'value': 'true'}
        ]

    def test_pipeline_no_input(self, tmp_path):
        @dsl.component
        def comp(boolean: bool = True) -> bool:
            return boolean

        @dsl.pipeline
        def pipeline_no_input():
            comp()

        manifest = compile_manifest(pipeline_no_input, tmp_path)
        (container,) = self.container_templates(manifest)
        assert container['inputs']['parameters'] == [
            {'name': 'boolean', 'default': 'true'}
        ]
        assert parameters(
            dag_tasks(root_template(manifest))['comp']['arguments']
        ) == {'boolean': 'true'}

    def test_pipeline_with_input(self, tmp_path):
        @dsl.component
        def comp(boolean: bool = True) -> bool:
            return boolean

        @dsl.pipeline
        def pipeline_with_input(boolean: bool = True):
            comp(boolean=boolean)

        manifest = compile_manifest(pipeline_with_input, tmp_path)
        (container,) = self.container_templates(manifest)
        assert container['inputs']['parameters'] == [
            {'name': 'boolean', 'default': 'true'}
        ]
        assert root_template(manifest)['inputs']['parameters'] == [
            {'name': 'boolean', 'default': 'true'}
        ]
        assert manifest['spec']['arguments']['parameters'] == [
            {'name': 'boolean', 'value': 'true'}
        ]

    def test_pipeline_with_with_overrides(self, tmp_path):
        @dsl.component
        def comp(boolean: bool = True) -> bool:
            return boolean

        @dsl.pipeline
        def pipeline_with_input(boolean: bool = False):
            comp(boolean=boolean)

        manifest = compile_manifest(
            pipeline_with_input, tmp_path, pipeline_parameters={'boolean': True}
        )
        (container,) = self.container_templates(manifest)
        assert container['inputs']['parameters'] == [
            {'name': 'boolean', 'default': 'true'}
        ]
        # The override binds the run argument; the declared default stays.
        assert manifest['spec']['arguments']['parameters'] == [
            {'name': 'boolean', 'value': 'true'}
        ]
        assert root_template(manifest)['inputs']['parameters'] == [
            {'name': 'boolean', 'default': 'false'}
        ]

    def test_constant_passed_to_component(self, tmp_path):
        @dsl.component
        def comp(boolean1: bool, boolean2: bool) -> bool:
            return boolean1

        @dsl.pipeline
        def my_pipeline():
            comp(boolean1=True, boolean2=False)

        manifest = compile_manifest(my_pipeline, tmp_path)
        assert parameters(
            dag_tasks(root_template(manifest))['comp']['arguments']
        ) == {'boolean1': 'true', 'boolean2': 'false'}
