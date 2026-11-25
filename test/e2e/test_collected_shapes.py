# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""``dsl.Collected`` shapes stock accepts that the native compiler once refused
(L03): a collection consumed inside a condition, and a collection across two
loop levels arriving as a list of lists."""

from typing import List

import pytest
from kfp import dsl

from e2e import support
from e2e.support import COMPONENT


@dsl.component(**COMPONENT)
def double(num: int) -> int:
    return num * 2


@dsl.component(**COMPONENT)
def add(nums: List[int]) -> int:
    assert all(isinstance(n, int) for n in nums), nums
    return sum(nums)


@dsl.component(**COMPONENT)
def add_two_ints(num1: int, num2: int) -> int:
    return num1 + num2


@dsl.component(**COMPONENT)
def add_nested(nums: List[List[int]]) -> int:
    import itertools

    assert all(isinstance(row, list) for row in nums), nums
    assert all(isinstance(n, int) for n in itertools.chain(*nums)), nums
    return sum(itertools.chain(*nums))


@dsl.pipeline(name='native-collected-in-condition')
def collected_in_condition(flag: str = 'yes'):
    with dsl.ParallelFor([1, 2, 3]) as v:
        t = double(num=v).set_caching_options(False)
    with dsl.Condition(flag == 'yes'):
        add(nums=dsl.Collected(t.output)).set_caching_options(False)


@dsl.pipeline(name='native-collected-nested-loops')
def collected_nested_loops() -> int:
    with dsl.ParallelFor([1, 2, 3]) as v1:
        with dsl.ParallelFor([10, 20]) as v2:
            t = add_two_ints(num1=v1, num2=v2).set_caching_options(False)
    return (
        add_nested(nums=dsl.Collected(t.output))
        .set_caching_options(False)
        .output
    )


@pytest.mark.full
def test_collection_consumed_inside_a_condition(client, record):
    submitted, done = support.run_pipeline(client, collected_in_condition)
    raw = support.workflow(client, done)
    assert done.state == 'SUCCEEDED', support.phases(raw)
    assert support.node_output(support.node(raw, 'add')) == '12'
    record(run_id=submitted.run_id, state=done.state)


@pytest.mark.full
def test_collection_across_two_loop_levels(client, record):
    submitted, done = support.run_pipeline(client, collected_nested_loops)
    raw = support.workflow(client, done)
    assert done.state == 'SUCCEEDED', support.phases(raw)
    # (1+10)+(1+20)+(2+10)+(2+20)+(3+10)+(3+20)
    root = raw['status']['nodes'][raw['metadata']['name']]
    assert support.node_output(root) == '102'
    record(run_id=submitted.run_id, state=done.state)


@dsl.pipeline(name='native-collected-skipped-iterations')
def collected_skipped_iterations() -> int:
    with dsl.ParallelFor([1, 2, 3]) as v:
        with dsl.Condition(v != 2):
            t = double(num=v).set_caching_options(False)
    return add(nums=dsl.Collected(t.output)).set_caching_options(False).output


@pytest.mark.full
def test_collection_omits_skipped_iterations(client, record):
    """A producer under a condition inside the loop: iterations whose
    condition was false contribute nothing, as in stock."""
    submitted, done = support.run_pipeline(client, collected_skipped_iterations)
    raw = support.workflow(client, done)
    assert done.state == 'SUCCEEDED', support.phases(raw)
    root = raw['status']['nodes'][raw['metadata']['name']]
    assert support.node_output(root) == '8'
    record(run_id=submitted.run_id, state=done.state)
