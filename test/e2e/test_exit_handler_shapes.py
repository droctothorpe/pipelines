# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Exit-handler shapes stock refused at compile time and native runs (A31):

a pipeline output returned from inside the handler, ``dsl.Collected`` over a
loop inside the handler consumed outside it, and nested handlers.
"""

import pytest
from kfp import dsl

from e2e import support
from e2e.support import COMPONENT


@dsl.component(**COMPONENT)
def echo(text: str) -> str:
    print(text)
    return text


@dsl.component(**COMPONENT)
def double(num: int) -> int:
    return num * 2


@dsl.component(**COMPONENT)
def add(nums: list) -> int:
    return sum(nums)


@dsl.pipeline(name='native-exit-return')
def exit_return(text: str = 'body') -> str:
    with dsl.ExitHandler(echo(text='exit task').set_caching_options(False)):
        return echo(text=text).set_caching_options(False).output


@dsl.pipeline(name='native-exit-collected')
def exit_collected() -> int:
    with dsl.ExitHandler(echo(text='exit task').set_caching_options(False)):
        with dsl.ParallelFor([1, 2, 3]) as v:
            t = double(num=v).set_caching_options(False)
    return add(nums=dsl.Collected(t.output)).set_caching_options(False).output


@dsl.pipeline(name='native-exit-nested')
def exit_nested():
    first = echo(text='First exit task.').set_caching_options(False)
    with dsl.ExitHandler(first):
        echo(text='Inside first exit handler.').set_caching_options(False)
        second = echo(text='Second exit task.').set_caching_options(False)
        with dsl.ExitHandler(second):
            echo(text='Inside second exit handler.').set_caching_options(False)


def _root_output(raw):
    return support.node_output(raw['status']['nodes'][raw['metadata']['name']])


@pytest.mark.full
def test_output_returned_from_inside_an_exit_handler(client, record):
    submitted, done = support.run_pipeline(client, exit_return)
    raw = support.workflow(client, done)
    assert done.state == 'SUCCEEDED', support.phases(raw)
    assert _root_output(raw) == 'body'
    assert support.node_output(support.node(raw, 'exit')) == 'exit task'
    record(run_id=submitted.run_id, state=done.state)


@pytest.mark.full
def test_collected_from_a_loop_inside_an_exit_handler(client, record):
    submitted, done = support.run_pipeline(client, exit_collected)
    raw = support.workflow(client, done)
    assert done.state == 'SUCCEEDED', support.phases(raw)
    assert _root_output(raw) == '12'
    record(run_id=submitted.run_id, state=done.state)


@pytest.mark.full
def test_nested_exit_handlers_both_run(client, record):
    submitted, done = support.run_pipeline(client, exit_nested)
    raw = support.workflow(client, done)
    assert done.state == 'SUCCEEDED', support.phases(raw)
    exits = sorted(
        support.node_output(n)
        for n in support.nodes(raw)
        if n['type'] == 'Pod' and n.get('displayName') == 'exit'
    )
    assert exits == ['First exit task.', 'Second exit task.']
    record(run_id=submitted.run_id, state=done.state)
