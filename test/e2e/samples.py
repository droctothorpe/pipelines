# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""The stock sample corpus as test cases: what to run, with which inputs, and
what outcome counts as a pass. The samples themselves are never edited."""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from e2e import support
from e2e.corpus import ROOT, definitions, sources

# Baseline sample defects fail stock compilation too; recorded in the inventory.
PREREQUISITES = {
    'artifact_previews/artifact_previews.py:artifact_preview_formats_pipeline': (
        'Eleven sequential pods each install polars, torch and transformers; '
        'allow about 20 minutes.'
    ),
    'kubernetes_pvc': 'Needs a PVC-capable workflow service account (KFP_TEST_SERVICE_ACCOUNT) '
    'and StorageClass standard.',
    'runtime_resource_request_gpu': 'Needs a GPU device plugin; the sample also uses an invalid '
    'resource name (inventory B05).',
    'parallel_join': 'Needs GCS access and a cloud-sdk image for this architecture.',
    'secret': 'Needs Google Cloud credentials; its python:3.7 image cannot install the SDK '
    'runtime (inventory B06).',
    'kfp_env_validation': 'Needs Google Cloud credentials and a repaired notebook (inventory B02).',
}
# The runner's recorded, smaller inputs for slow samples; not the notebook defaults.
PARAMETERS = {
    '/caching/': {'seconds': 1},
    '/resource_spec/resource_spec.py': {'n': 10000},
    '/resource_spec/runtime_resource_request.py': {'n': 10000},
    '/condition/condition_v2.py': {'force_flip_result': 'heads'},
}
# Samples whose body fails on purpose to demonstrate exit handling.
EXPECTED_FAILED = ('/exit_handler/', '/DSL - Control structures/')
LONG = {'artifact_preview_formats_pipeline': 1500}


@dataclass
class Case:
    source: str
    pipeline: str
    function: object = None
    load_error: str = None
    parameters: dict = field(default_factory=dict)
    expected_state: str = 'SUCCEEDED'
    prerequisite: str = None
    timeout: int = 600
    # The stock runner test's assertions for this sample, on native state.
    expect: Callable = None

    @property
    def id(self):
        return self.source.removeprefix('samples/') + ':' + self.pipeline

    @property
    def key(self):
        return self.source.removeprefix('samples/core/') + ':' + self.pipeline


def cases():
    """One case per pipeline definition under samples/, in corpus order."""
    result = []
    for path, source in sources():
        namespace, names, error = definitions(path, source)
        relative = str(path.relative_to(ROOT))
        for name in names:
            case = Case(source=relative, pipeline=name)
            if name in namespace:
                case.function = namespace[name]
            else:
                case.load_error = error
            for marker, parameters in PARAMETERS.items():
                if marker in relative:
                    case.parameters = dict(parameters)
            if any(marker in relative for marker in EXPECTED_FAILED):
                case.expected_state = 'FAILED'
            for key, reason in PREREQUISITES.items():
                if key in relative or key == case.key:
                    case.prerequisite = reason
            case.timeout = LONG.get(name, case.timeout)
            case.expect = EXPECTATIONS.get(case.key)
            result.append(case)
    return result


def frozen_baseline():
    """The captured stock compile results, to tell baseline failures apart."""
    fixture = json.loads((ROOT / 'test/data/stock_samples.json').read_text())
    return {
        row['source'] + ':' + row['pipeline']: row['compile']
        for row in fixture['samples']
    }


@dataclass
class Outcome:
    """One completed submission of a sample: the run, its Argo workflow, and
    `rerun(arguments)` to submit the same package again with other inputs.

    Stock's runner asserted on MLMD executions; the same facts are read
    here from workflow nodes (phase, inputs, outputs, memoization) and
    from the run's tasks.
    """

    client: object
    done: object
    raw: dict
    cold: bool
    rerun: Callable

    @property
    def nodes(self):
        return support.nodes(self.raw)

    def pods(self, display_name):
        return [
            n
            for n in self.nodes
            if n.get('type') == 'Pod' and n.get('displayName') == display_name
        ]

    def pod(self, display_name):
        found = self.pods(display_name)
        assert len(found) == 1, (display_name, support.phases(self.raw))
        return found[0]

    def children(self, entry):
        """Nodes whose boundary is `entry`: a DAG's direct tasks."""
        return [n for n in self.nodes if n.get('boundaryID') == entry['id']]

    def names(self, entries):
        return sorted(n.get('displayName') for n in entries)

    def top_level(self):
        return self.children({'id': self.raw['metadata']['name']})

    def iterations(self, loop_name):
        """The expanded iteration nodes of a ParallelFor group."""
        loop = support.node(self.raw, loop_name)
        groups = [
            n for n in self.children(loop) if n.get('type') == 'TaskGroup'
        ]
        assert groups, (loop_name, support.phases(self.raw))
        nodes = self.raw['status']['nodes']
        return [nodes[i] for g in groups for i in g.get('children', [])]


EXPECTATIONS = {}


def expectation(*keys):
    """Register the stock assertions for the sample cases named by `keys`
    (``<path under samples/core>:<pipeline>``)."""

    def register(function):
        for key in keys:
            EXPECTATIONS[key] = function
        return function

    return register


def _hit(entry):
    return bool(entry.get('memoizationStatus', {}).get('hit'))


def _time(stamp):
    return datetime.fromisoformat(stamp.replace('Z', '+00:00'))


def _after(later, earlier):
    assert _time(later['startedAt']) >= _time(earlier['finishedAt']), (
        earlier,
        later,
    )


@expectation(
    'caching/caching.ipynb:caching_pipeline',
    'caching/caching_sample.py:caching_pipeline',
)
def caching_reuses_the_first_result(outcome):
    """Stock ran the pipeline twice and required the second run to finish
    before the work could have; here the second run's task is a cache hit that
    reproduces the first run's output."""
    first = outcome.pod('do-work-op')
    datetime.fromisoformat(support.node_output(first))
    if outcome.cold:
        assert not _hit(first), first
        return {'cache': 'disabled'}
    second = outcome.rerun()
    assert second.done.state == 'SUCCEEDED', support.phases(second.raw)
    reused = second.pod('do-work-op')
    assert _hit(reused), reused
    assert support.node_output(reused) == support.node_output(first)
    assert support.task(second.done, 'do-work-op').state == 'CACHED'
    return {'cache': 'hit'}


@expectation(
    'caching/caching.ipynb:caching_pipeline3',
    'caching/caching_sample.py:caching_pipeline3',
)
def caching_disabled_performs_the_work(outcome):
    """Stock required this run to take the full working time; the task must
    execute rather than be served from the cache."""
    work = outcome.pod('do-work-op')
    assert work['phase'] == 'Succeeded', work
    assert not work.get('memoizationStatus'), work
    assert support.task(outcome.done, 'do-work-op').state == 'SUCCEEDED'
    datetime.fromisoformat(support.node_output(work))


@expectation('condition/condition_v2.py:condition')
def condition_runs_the_branch_only_for_heads(outcome):
    """Heads runs the branch with its three tasks; a tails rerun skips it with
    no children (stock: NotTriggered)."""
    branch_tasks = ['flip-coin-2', 'print-msg-2', 'print-msg-3']
    assert outcome.names(outcome.top_level()) == [
        'condition-1',
        'flip-coin',
        'print-msg',
    ]
    assert support.node_output(outcome.pod('flip-coin')) == 'heads'
    assert support.node_input(outcome.pod('print-msg'), 'msg') == 'heads'
    branch = support.node(outcome.raw, 'condition-1')
    assert branch['phase'] == 'Succeeded', branch
    assert outcome.names(outcome.children(branch)) == branch_tasks
    assert support.node_input(
        outcome.pod('print-msg-2'), 'msg'
    ) == support.node_output(outcome.pod('flip-coin-2'))
    assert (
        support.node_input(outcome.pod('print-msg-3'), 'msg')
        == 'condition test'
    )

    tails = outcome.rerun({'force_flip_result': 'tails'})
    assert tails.done.state == 'SUCCEEDED', support.phases(tails.raw)
    assert tails.names(tails.top_level()) == [
        'condition-1',
        'flip-coin',
        'print-msg',
    ]
    assert support.node_input(tails.pod('print-msg'), 'msg') == 'tails'
    skipped = support.node(tails.raw, 'condition-1')
    assert skipped['phase'] == 'Skipped', skipped
    assert not tails.children(skipped), support.phases(tails.raw)
    assert not any(tails.pods(name) for name in branch_tasks)
    assert support.task(tails.done, 'condition-1').state == 'SKIPPED'


@expectation('condition/nested_condition.py:my_pipeline')
def nested_condition_follows_the_coin_flips(outcome):
    """The outer condition always holds; the inner one runs exactly when the
    second and third flips agree."""
    assert outcome.names(outcome.top_level()) == [
        'condition-1',
        'flip-coin-op',
        'flip-coin-op-2',
        'print-op',
        'print-op-2',
    ]
    outer = support.node(outcome.raw, 'condition-1')
    assert outer['phase'] == 'Succeeded', outer
    assert outcome.names(outcome.children(outer)) == [
        'condition-2',
        'flip-coin-op-3',
        'print-op-3',
    ]
    flips = {}
    for suffix in ('', '-2', '-3'):
        flips[suffix] = support.node_output(
            outcome.pod('flip-coin-op' + suffix)
        )
        assert flips[suffix] in ('heads', 'tails'), flips
        assert (
            support.node_input(outcome.pod('print-op' + suffix), 'msg')
            == flips[suffix]
        )
    inner = support.node(outcome.raw, 'condition-2')
    if flips['-2'] == flips['-3']:
        assert inner['phase'] == 'Succeeded', inner
        assert outcome.names(outcome.children(inner)) == [
            'flip-coin-op-4',
            'print-op-4',
        ]
        assert support.node_input(
            outcome.pod('print-op-4'), 'msg'
        ) == support.node_output(outcome.pod('flip-coin-op-4'))
    else:
        assert inner['phase'] == 'Skipped', inner
        assert not outcome.children(inner), support.phases(outcome.raw)
    return {'inner_condition': inner['phase']}


@expectation('execution_order/execution_order.py:execution_order_pipeline')
def execution_order_runs_the_second_step_after_the_first(outcome):
    first, second = outcome.pod('echo1-op'), outcome.pod('echo2-op')
    assert support.node_input(first, 'text1') == 'message 1'
    assert support.node_input(second, 'text2') == 'message 2'
    assert first['phase'] == second['phase'] == 'Succeeded'
    _after(second, first)


@expectation('exit_handler/exit_handler.py:pipeline_exit_handler')
def exit_handler_runs_after_the_failing_body(outcome):
    """Stock checked the exit task's input message and the task set; the body
    here fails deliberately, so the run is FAILED (asserted by the sweep) while
    the handler still runs last and succeeds."""
    assert outcome.names(
        n for n in outcome.nodes if n.get('type') == 'Pod'
    ) == ['exit', 'fail-op', 'print-op-2']
    printed = outcome.pod('print-op-2')
    assert printed['phase'] == 'Succeeded', printed
    assert support.node_input(printed, 'message') == 'Hello World!'
    failed = outcome.pod('fail-op')
    assert failed['phase'] == 'Failed', failed
    assert support.node_input(failed, 'message') == 'Task failed.'
    cleanup = outcome.pod('exit')
    assert cleanup['phase'] == 'Succeeded', cleanup
    assert support.node_input(cleanup, 'message') == 'Exit handler has worked!'
    _after(cleanup, failed)
    _after(cleanup, printed)


@expectation('loop_output/loop_output.py:my_pipeline')
def loop_output_iterates_over_the_generated_list(outcome):
    items = ['1.1', '1.2', '1.3']
    assert outcome.names(outcome.top_level()) == [
        'args-generator-op',
        'for-loop-1',
    ]
    generated = support.node_output(outcome.pod('args-generator-op'))
    assert json.loads(generated) == items, generated
    iterations = outcome.iterations('for-loop-1')
    assert len(iterations) == 3, support.phases(outcome.raw)
    assert all(n['phase'] == 'Succeeded' for n in iterations), iterations
    prints = outcome.pods('print-op')
    assert sorted(support.node_input(p, 's') for p in prints) == items
    assert all(p['phase'] == 'Succeeded' for p in prints), prints
    assert [
        len([p for p in prints if p['boundaryID'] == i['id']])
        for i in iterations
    ] == [1, 1, 1]
    return {'iterations': len(iterations)}


@expectation('loop_parallelism/loop_parallelism.py:pipeline')
def loop_parallelism_runs_both_tasks_per_item(outcome):
    assert outcome.names(outcome.top_level()) == ['for-loop-2']
    iterations = outcome.iterations('for-loop-2')
    assert len(iterations) == 2, support.phases(outcome.raw)
    assert all(n['phase'] == 'Succeeded' for n in iterations), iterations
    for name, values in (('print-op', [1, 10]), ('print-op-2', [2, 20])):
        pods = outcome.pods(name)
        assert sorted(int(support.node_input(p, 's')) for p in pods) == values
        assert all(p['phase'] == 'Succeeded' for p in pods), pods
    return {'iterations': len(iterations)}


@expectation('loop_parameter/loop_parameter.py:my_pipeline')
def loop_parameter_concatenates_each_generated_item(outcome):
    assert outcome.names(outcome.top_level()) == [
        'for-loop-1',
        'generate-op',
        'print-op',
    ]
    assert (
        support.node_output(outcome.pod('print-op'))
        == 'this is a test for looping through parameters'
    )
    generated = support.node_output(outcome.pod('generate-op'))
    assert json.loads(generated) == [
        {'a': i, 'b': i * 10} for i in range(1, 5)
    ], generated
    iterations = outcome.iterations('for-loop-1')
    assert len(iterations) == 4, support.phases(outcome.raw)
    assert all(n['phase'] == 'Succeeded' for n in iterations), iterations
    assert sorted(
        (support.node_input(p, 'a'), support.node_input(p, 'b'))
        for p in outcome.pods('concat-op')
    ) == [('1', '10'), ('2', '20'), ('3', '30'), ('4', '40')]
    assert sorted(
        support.node_output(p) for p in outcome.pods('print-op-2')
    ) == ['110', '220', '330', '440']
    return {'iterations': len(iterations)}


@expectation('loop_static/loop_static.py:my_pipeline')
def loop_static_concatenates_each_literal_item(outcome):
    assert outcome.names(outcome.top_level()) == ['for-loop-2', 'print-op']
    iterations = outcome.iterations('for-loop-2')
    assert len(iterations) == 2, support.phases(outcome.raw)
    assert all(n['phase'] == 'Succeeded' for n in iterations), iterations
    assert sorted(
        (support.node_input(p, 'a'), support.node_input(p, 'b'))
        for p in outcome.pods('concat-op')
    ) == [('1', '2'), ('10', '20')]
    assert sorted(
        support.node_output(p) for p in outcome.pods('print-op-2')
    ) == ['1020', '12']
    return {'iterations': len(iterations)}


@expectation('multiple_outputs/multiple_outputs.ipynb:pipeline')
def multiple_outputs_feed_the_third_task(outcome):
    """product_sum(2, 2.5) and product_sum(2.5, 3) feed product_sum(5, 5.5);
    outputs are compared numerically since the runtime chooses the float
    spelling."""
    expected = {
        'product-sum': (5.0, 4.5),
        'product-sum-2': (7.5, 5.5),
        'product-sum-3': (27.5, 10.5),
    }
    for name, (product, total) in expected.items():
        entry = outcome.pod(name)
        assert entry['phase'] == 'Succeeded', entry
        assert float(support.node_output(entry, 'product')) == product, entry
        assert float(support.node_output(entry, 'sum')) == total, entry
    third = outcome.pod('product-sum-3')
    assert float(support.node_input(third, 'a')) == 5.0, third
    assert float(support.node_input(third, 'b')) == 5.5, third


@expectation('output_a_directory/output_a_directory.py:dir_pipeline')
def output_a_directory_is_consumed_by_uri(outcome):
    producer = outcome.pod('produce-dir-with-files-python-op')
    consumer = outcome.pod('list-dir-files-python')
    assert producer['phase'] == consumer['phase'] == 'Succeeded'
    assert support.node_input(producer, 'num_files') == '15'
    assert support.node_input(producer, 'subdir') == 'texts'
    artifacts = [
        a['name'] for a in producer.get('outputs', {}).get('artifacts', [])
    ]
    assert 'output_dir' in artifacts, producer
    uri = support.node_output(producer, 'kfp-uri-output_dir')
    assert uri.startswith(('s3://', 'gs://')) and '{{' not in uri, uri
    assert support.node_input(consumer, 'kfp-uri-input_dir') == uri
    assert support.node_input(consumer, 'subdir') == 'texts'
    _after(consumer, producer)


@expectation(
    'resource_spec/resource_spec.py:my_pipeline',
    'resource_spec/runtime_resource_request.py:resource_request_pipeline',
)
def resource_spec_fits_then_exceeds_its_memory_limit(outcome):
    """Stock ran the default input to success and n=21234567 to an OOM failure
    under the sample's memory limit."""
    training = outcome.pod('training-op')
    assert training['phase'] == 'Succeeded', training
    assert support.node_output(training) == support.node_input(training, 'n')
    if outcome.pods('generate-resource-request'):
        request = outcome.pod('generate-resource-request')
        assert support.node_output(request, 'memory') == '500Mi'
        assert support.node_output(request, 'cpu') == '200m'
    oom = outcome.rerun({'n': 21234567})
    assert oom.done.state == 'FAILED', support.phases(oom.raw)
    failed = oom.pod('training-op')
    assert failed['phase'] in ('Failed', 'Error'), failed
    return {'oom_message': failed.get('message')}


@expectation('retry/retry.py:retry_sample_pipeline')
def retry_succeeds_within_the_attempt_limits(outcome):
    """Each randomly failing task ends in success within its retry limit, with
    every earlier attempt failed."""
    attempts = {}
    for name, limit in (('random-failure-op', 10), ('random-failure-op-2', 5)):
        parent = support.node(outcome.raw, name)
        assert parent['phase'] == 'Succeeded', parent
        if _hit(parent):
            attempts[name] = 'cached'
            continue
        nodes = outcome.raw['status']['nodes']
        tries = [
            nodes[i]
            for i in parent.get('children', [])
            if nodes[i].get('type') == 'Pod'
        ]
        if parent.get('type') == 'Pod':
            tries = [parent]
        assert 1 <= len(tries) <= limit + 1, tries
        assert all(t['phase'] == 'Failed' for t in tries[:-1]), tries
        assert tries[-1]['phase'] == 'Succeeded', tries
        attempts[name] = len(tries)
    return {'attempts': attempts}


def verify_previews(client, done, namespace, workflow_name, nodes, disabled):
    """The artifact preview samples publish previews for every artifact unless
    the pipeline disables them; URIs must be concrete S3 locations."""
    count = 0
    transport = client._run_api.transport
    for entry in nodes.values():
        if entry.get('type') != 'Pod' or entry.get('phase') != 'Succeeded':
            continue
        metadata = transport.request(
            'GET',
            f'/argo/artifacts/{namespace}/{workflow_name}/{entry["id"]}/kfp-metadata',
        )
        for artifact in metadata.get('artifacts', []):
            descriptor = artifact['metadata'].get('_kfp_preview')
            assert bool(descriptor) is not disabled, artifact
            if descriptor:
                preview = transport.request(
                    'GET',
                    f'/argo/artifacts/{namespace}/{workflow_name}/{entry["id"]}/{artifact["port"]}-preview',
                )
                assert preview, artifact
                count += 1
    for entry in nodes.values():
        for parameter in entry.get('outputs', {}).get('parameters', []):
            if parameter['name'] in (
                'kfp-uri-datasets',
                'kfp-uri-models',
                'kfp-uri-dataframes',
                'kfp-uri-pytorch_models',
            ):
                values = json.loads(parameter['value'])
                assert values and all(
                    isinstance(v, str)
                    and v.startswith('s3://')
                    and '{{' not in v
                    for v in values
                ), values
    if not disabled:
        assert count > 0, 'No artifact previews were generated'
    return count


def compile_case(case, directory: Path):
    from kfp import compiler

    target = directory / (case.id.replace('/', '_').replace(':', '-') + '.yaml')
    compiler.Compiler().compile(case.function, str(target))
    return target
