# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Stock's kfp.kubernetes unit tests for tolerations, node selectors and node
affinity, ported to the native boundary.

See ``setters_test.py`` for the approach and the shared helpers.
"""

import copy

import pytest

from kfp import dsl, kubernetes
from kfp.kubernetes.setters_test import (
    comp,
    comp_with_output,
    lowered,
    pipeline_input,
    recorded,
    secret_as_volume,
    task_output,
)


class TestTolerations:
    def test_add_one(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.add_toleration(
                task,
                key='key1',
                operator='Equal',
                value='value1',
                effect='NoSchedule',
            )

        toleration = {
            'key': 'key1',
            'operator': 'Equal',
            'value': 'value1',
            'effect': 'NoSchedule',
        }
        assert recorded(my_pipeline) == {
            'exec-comp': {'tolerations': [toleration]}
        }
        assert lowered(my_pipeline)['comp']['tolerations'] == [toleration]

    def test_add_one_with_toleration_seconds(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.add_toleration(
                task,
                key='key1',
                operator='Equal',
                value='value1',
                effect='NoExecute',
                toleration_seconds=10,
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'tolerations': [
                    {
                        'key': 'key1',
                        'operator': 'Equal',
                        'value': 'value1',
                        'effect': 'NoExecute',
                        'tolerationSeconds': '10',
                    }
                ]
            }
        }
        assert (
            lowered(my_pipeline)['comp']['tolerations'][0]['tolerationSeconds']
            == 10
        ), 'The pod field is an integer, not the recorded int64 string'

    def test_add_two(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.add_toleration(
                task, key='key1', operator='Equal', value='value1'
            )
            kubernetes.add_toleration(
                task, key='key2', operator='Equal', value='value2'
            )

        tolerations = [
            {'key': 'key1', 'operator': 'Equal', 'value': 'value1'},
            {'key': 'key2', 'operator': 'Equal', 'value': 'value2'},
        ]
        assert recorded(my_pipeline) == {
            'exec-comp': {'tolerations': tolerations}
        }
        assert lowered(my_pipeline)['comp']['tolerations'] == tolerations

    def test_respects_other_configuration(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.use_secret_as_volume(
                task, secret_name='my-secret', mount_path='/mnt/my_vol'
            )
            kubernetes.add_toleration(
                task, key='key1', operator='Equal', value='value1'
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'tolerations': [
                    {'key': 'key1', 'operator': 'Equal', 'value': 'value1'}
                ],
                'secretAsVolume': [
                    secret_as_volume('my-secret', '/mnt/my_vol')
                ],
            }
        }


class TestTolerationsJSON:
    def test_component_pipeline_input_one(self):
        @dsl.pipeline
        def my_pipeline(toleration_input: dict):
            task = comp()
            kubernetes.add_toleration_json(
                task, toleration_json=toleration_input
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'tolerations': [
                    {'tolerationJson': pipeline_input('toleration_input')}
                ]
            }
        }
        template = lowered(my_pipeline)['comp']
        assert 'tolerations' not in template
        assert 'tolerations' in template['podSpecPatch'], (
            'A runtime toleration resolves through the pod spec patch'
        )

    def test_component_pipeline_input_two(self):
        @dsl.pipeline
        def my_pipeline(toleration_input_1: dict, toleration_input_2: list):
            t1 = comp()
            kubernetes.add_toleration_json(
                t1, toleration_json=toleration_input_1
            )
            t2 = comp()
            kubernetes.add_toleration_json(
                t2, toleration_json=toleration_input_1
            )
            kubernetes.add_toleration_json(
                t2, toleration_json=toleration_input_2
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'tolerations': [
                    {'tolerationJson': pipeline_input('toleration_input_1')}
                ]
            },
            'exec-comp-2': {
                'tolerations': [
                    {'tolerationJson': pipeline_input('toleration_input_1')},
                    {'tolerationJson': pipeline_input('toleration_input_2')},
                ]
            },
        }

    def test_component_pipeline_input_three(self):
        @dsl.pipeline
        def my_pipeline(toleration_input: dict):
            t1 = comp()
            kubernetes.add_toleration_json(t1, toleration_json=toleration_input)
            kubernetes.add_toleration_json(
                t1,
                toleration_json={
                    'key': 'key3',
                    'operator': 'Equal',
                    'value': 'value3',
                    'effect': 'NoSchedule',
                },
            )
            kubernetes.add_toleration_json(
                t1,
                toleration_json=[
                    {
                        'key': 'key1',
                        'operator': 'Equal',
                        'value': 'value1',
                        'effect': 'NoSchedule',
                    },
                    {
                        'key': 'key2',
                        'operator': 'Exists',
                        'effect': 'NoExecute',
                    },
                ],
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'tolerations': [
                    {'tolerationJson': pipeline_input('toleration_input')},
                    {
                        'key': 'key3',
                        'operator': 'Equal',
                        'value': 'value3',
                        'effect': 'NoSchedule',
                    },
                    {
                        'key': 'key1',
                        'operator': 'Equal',
                        'value': 'value1',
                        'effect': 'NoSchedule',
                    },
                    {
                        'key': 'key2',
                        'operator': 'Exists',
                        'effect': 'NoExecute',
                    },
                ]
            }
        }

    def test_static_dict_camel_case_toleration_seconds(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.add_toleration_json(
                task,
                toleration_json={
                    'key': 'key1',
                    'operator': 'Equal',
                    'value': 'value1',
                    'effect': 'NoExecute',
                    'tolerationSeconds': 300,
                },
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'tolerations': [
                    {
                        'key': 'key1',
                        'operator': 'Equal',
                        'value': 'value1',
                        'effect': 'NoExecute',
                        'tolerationSeconds': '300',
                    }
                ]
            }
        }

    def test_static_list_camel_case_toleration_seconds(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.add_toleration_json(
                task,
                toleration_json=[
                    {
                        'key': 'key1',
                        'operator': 'Equal',
                        'value': 'value1',
                        'effect': 'NoExecute',
                        'tolerationSeconds': 300,
                    },
                    {
                        'key': 'key2',
                        'operator': 'Equal',
                        'value': 'value2',
                        'effect': 'NoExecute',
                        'tolerationSeconds': 60,
                    },
                ],
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'tolerations': [
                    {
                        'key': 'key1',
                        'operator': 'Equal',
                        'value': 'value1',
                        'effect': 'NoExecute',
                        'tolerationSeconds': '300',
                    },
                    {
                        'key': 'key2',
                        'operator': 'Equal',
                        'value': 'value2',
                        'effect': 'NoExecute',
                        'tolerationSeconds': '60',
                    },
                ]
            }
        }
        assert [
            t['tolerationSeconds']
            for t in lowered(my_pipeline)['comp']['tolerations']
        ] == [300, 60]

    def test_static_dict_camel_case_zero_toleration_seconds(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.add_toleration_json(
                task,
                toleration_json={
                    'key': 'key1',
                    'operator': 'Equal',
                    'value': 'value1',
                    'effect': 'NoExecute',
                    'tolerationSeconds': 0,
                },
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'tolerations': [
                    {
                        'key': 'key1',
                        'operator': 'Equal',
                        'value': 'value1',
                        'effect': 'NoExecute',
                        'tolerationSeconds': '0',
                    }
                ]
            }
        }
        assert (
            lowered(my_pipeline)['comp']['tolerations'][0]['tolerationSeconds']
            == 0
        )

    def test_static_snake_case_toleration_seconds_still_supported(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.add_toleration_json(
                task,
                toleration_json={
                    'key': 'key1',
                    'operator': 'Equal',
                    'value': 'value1',
                    'effect': 'NoExecute',
                    'toleration_seconds': 50,
                },
            )
            kubernetes.add_toleration_json(
                task,
                toleration_json=[
                    {
                        'key': 'key2',
                        'operator': 'Equal',
                        'value': 'value2',
                        'effect': 'NoExecute',
                        'toleration_seconds': 0,
                    }
                ],
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'tolerations': [
                    {
                        'key': 'key1',
                        'operator': 'Equal',
                        'value': 'value1',
                        'effect': 'NoExecute',
                        'tolerationSeconds': '50',
                    },
                    {
                        'key': 'key2',
                        'operator': 'Equal',
                        'value': 'value2',
                        'effect': 'NoExecute',
                        'tolerationSeconds': '0',
                    },
                ]
            }
        }

    def test_static_omitted_toleration_seconds(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.add_toleration_json(
                task,
                toleration_json={
                    'key': 'key1',
                    'operator': 'Equal',
                    'value': 'value1',
                    'effect': 'NoSchedule',
                },
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'tolerations': [
                    {
                        'key': 'key1',
                        'operator': 'Equal',
                        'value': 'value1',
                        'effect': 'NoSchedule',
                    }
                ]
            }
        }

    def test_static_camel_case_input_is_not_mutated(self):
        input_dict = {
            'key': 'key1',
            'operator': 'Equal',
            'value': 'value1',
            'effect': 'NoExecute',
            'tolerationSeconds': 300,
        }
        input_list = [
            {
                'key': 'key2',
                'operator': 'Equal',
                'value': 'value2',
                'effect': 'NoExecute',
                'tolerationSeconds': 60,
            },
            {
                'key': 'key3',
                'operator': 'Equal',
                'value': 'value3',
                'effect': 'NoExecute',
                'tolerationSeconds': 0,
            },
        ]
        expected_dict = copy.deepcopy(input_dict)
        expected_list = copy.deepcopy(input_list)

        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.add_toleration_json(task, toleration_json=input_dict)
            kubernetes.add_toleration_json(task, toleration_json=input_list)

        assert input_dict == expected_dict
        assert input_list == expected_list

    def test_component_upstream_input_one(self):
        @dsl.pipeline
        def my_pipeline():
            t1 = comp()
            t2 = comp_with_output()
            kubernetes.add_toleration_json(t1, toleration_json=t2.output)

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'tolerations': [
                    {'tolerationJson': task_output('comp-with-output')}
                ]
            }
        }

    def test_component_upstream_input_two(self):
        @dsl.pipeline
        def my_pipeline():
            t1 = comp()
            t2 = comp_with_output()
            t3 = comp_with_output()
            t4 = comp_with_output()
            kubernetes.add_toleration_json(t1, toleration_json=t2.output)
            t5 = comp()
            kubernetes.add_toleration_json(t5, toleration_json=t3.output)
            kubernetes.add_toleration_json(t5, toleration_json=t4.output)

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'tolerations': [
                    {'tolerationJson': task_output('comp-with-output')}
                ]
            },
            'exec-comp-2': {
                'tolerations': [
                    {'tolerationJson': task_output('comp-with-output-2')},
                    {'tolerationJson': task_output('comp-with-output-3')},
                ]
            },
        }

    @pytest.mark.parametrize('operator', ['Equal', 'Exists', 'Gt', 'Lt'])
    def test_valid_operators(self, operator):
        @dsl.pipeline
        def my_pipeline():
            kubernetes.add_toleration(comp(), key='k', operator=operator)

        tolerations = recorded(my_pipeline)['exec-comp']['tolerations']
        assert tolerations[0]['operator'] == operator

    @pytest.mark.parametrize(
        'effect', ['NoExecute', 'NoSchedule', 'PreferNoSchedule']
    )
    def test_valid_effects(self, effect):
        @dsl.pipeline
        def my_pipeline():
            kubernetes.add_toleration(comp(), key='k', effect=effect)

        tolerations = recorded(my_pipeline)['exec-comp']['tolerations']
        assert tolerations[0]['effect'] == effect

    @pytest.mark.parametrize('operator,effect', [(None, None), ('', '')])
    def test_omitted_or_empty_operator_and_effect(self, operator, effect):
        @dsl.pipeline
        def my_pipeline():
            kubernetes.add_toleration(
                comp(), key='k', operator=operator, effect=effect
            )

        assert recorded(my_pipeline)['exec-comp']['tolerations'] == [
            {'key': 'k'}
        ]
        assert lowered(my_pipeline)['comp']['tolerations'] == [{'key': 'k'}]

    def test_invalid_operator_raises(self):
        with pytest.raises(
            ValueError, match="Invalid toleration operator 'Bad'"
        ):

            @dsl.pipeline
            def my_pipeline():
                kubernetes.add_toleration(comp(), key='k', operator='Bad')

    def test_invalid_effect_raises(self):
        with pytest.raises(ValueError, match="Invalid toleration effect 'Bad'"):

            @dsl.pipeline
            def my_pipeline():
                kubernetes.add_toleration(comp(), key='k', effect='Bad')

    @pytest.mark.parametrize(
        'toleration_json',
        [
            {'key': 'k', 'operator': 'Bad'},
            {'key': 'k', 'effect': 'Bad'},
            [{'key': 'k', 'operator': 'Equal'}, {'key': 'k', 'effect': 'Bad'}],
        ],
    )
    def test_add_toleration_json_static_invalid_raises(self, toleration_json):
        with pytest.raises(ValueError, match='Invalid toleration'):

            @dsl.pipeline
            def my_pipeline():
                kubernetes.add_toleration_json(comp(), toleration_json)

    def test_add_toleration_json_invalid_type_raises(self):
        with pytest.raises(
            ValueError,
            match='toleration_json must be a dict, list, or input parameter',
        ):

            @dsl.pipeline
            def my_pipeline():
                kubernetes.add_toleration_json(comp(), 'key=value')

    def test_add_toleration_json_static_valid_gt(self):
        @dsl.pipeline
        def my_pipeline():
            kubernetes.add_toleration_json(
                comp(),
                {
                    'key': 'k',
                    'operator': 'Gt',
                    'value': '5',
                    'effect': 'NoSchedule',
                },
            )

        tolerations = recorded(my_pipeline)['exec-comp']['tolerations']
        assert tolerations[0]['operator'] == 'Gt'


class TestNodeSelector:
    def test_add_one(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.add_node_selector(
                task,
                label_key='cloud.google.com/gke-accelerator',
                label_value='nvidia-tesla-p4',
            )

        labels = {'cloud.google.com/gke-accelerator': 'nvidia-tesla-p4'}
        assert recorded(my_pipeline) == {
            'exec-comp': {'nodeSelector': {'labels': labels}}
        }
        assert lowered(my_pipeline)['comp']['nodeSelector'] == labels

    def test_add_two(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.add_node_selector(
                task,
                label_key='cloud.google.com/gke-accelerator',
                label_value='nvidia-tesla-p4',
            )
            kubernetes.add_node_selector(
                task,
                label_key='other_label_key',
                label_value='other_label_value',
            )

        labels = {
            'cloud.google.com/gke-accelerator': 'nvidia-tesla-p4',
            'other_label_key': 'other_label_value',
        }
        assert recorded(my_pipeline) == {
            'exec-comp': {'nodeSelector': {'labels': labels}}
        }
        assert lowered(my_pipeline)['comp']['nodeSelector'] == labels

    def test_respects_other_configuration(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.use_secret_as_volume(
                task, secret_name='my-secret', mount_path='/mnt/my_vol'
            )
            kubernetes.add_node_selector(
                task,
                label_key='cloud.google.com/gke-accelerator',
                label_value='nvidia-tesla-p4',
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'nodeSelector': {
                    'labels': {
                        'cloud.google.com/gke-accelerator': 'nvidia-tesla-p4'
                    }
                },
                'secretAsVolume': [
                    secret_as_volume('my-secret', '/mnt/my_vol')
                ],
            }
        }


class TestNodeSelectorJSON:
    def test_component_pipeline_input_one(self):
        @dsl.pipeline
        def my_pipeline(selector_input: str):
            task = comp()
            kubernetes.add_node_selector_json(
                task, node_selector_json=selector_input
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'nodeSelector': {
                    'nodeSelectorJson': pipeline_input('selector_input')
                }
            }
        }
        template = lowered(my_pipeline)['comp']
        assert 'nodeSelector' not in template
        assert 'nodeSelector' in template['podSpecPatch']

    def test_component_pipeline_input_two(self):
        @dsl.pipeline
        def my_pipeline(selector_input_1: str, selector_input_2: str):
            t1 = comp()
            kubernetes.add_node_selector_json(
                t1, node_selector_json=selector_input_1
            )
            t2 = comp()
            kubernetes.add_node_selector_json(
                t2, node_selector_json=selector_input_1
            )
            # Applying a second selector JSON replaces the first.
            kubernetes.add_node_selector_json(
                t2, node_selector_json=selector_input_2
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'nodeSelector': {
                    'nodeSelectorJson': pipeline_input('selector_input_1')
                }
            },
            'exec-comp-2': {
                'nodeSelector': {
                    'nodeSelectorJson': pipeline_input('selector_input_2')
                }
            },
        }

    def test_component_upstream_input_one(self):
        @dsl.pipeline
        def my_pipeline():
            t1 = comp()
            t2 = comp_with_output()
            kubernetes.add_node_selector_json(t1, node_selector_json=t2.output)

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'nodeSelector': {
                    'nodeSelectorJson': task_output('comp-with-output')
                }
            }
        }

    def test_component_upstream_input_two(self):
        @dsl.pipeline
        def my_pipeline(selector_input: str):
            t1 = comp()
            t2 = comp_with_output()
            kubernetes.add_node_selector_json(t1, node_selector_json=t2.output)
            t3 = comp()
            t4 = comp_with_output()
            kubernetes.add_node_selector_json(t3, node_selector_json=t4.output)
            t5 = comp_with_output()
            kubernetes.add_node_selector_json(t3, node_selector_json=t5.output)

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'nodeSelector': {
                    'nodeSelectorJson': task_output('comp-with-output')
                }
            },
            'exec-comp-2': {
                'nodeSelector': {
                    'nodeSelectorJson': task_output('comp-with-output-3')
                }
            },
        }


class TestNodeAffinity:
    def test_add_match_expressions(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.add_node_affinity(
                task,
                match_expressions=[
                    {
                        'key': 'disktype',
                        'operator': 'In',
                        'values': ['ssd', 'nvme'],
                    }
                ],
            )

        term = {
            'matchExpressions': [
                {'key': 'disktype', 'operator': 'In', 'values': ['ssd', 'nvme']}
            ]
        }
        assert recorded(my_pipeline) == {'exec-comp': {'nodeAffinity': [term]}}
        assert lowered(my_pipeline)['comp']['affinity'] == {
            'nodeAffinity': {
                'requiredDuringSchedulingIgnoredDuringExecution': {
                    'nodeSelectorTerms': [term]
                }
            }
        }

    def test_add_match_fields(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.add_node_affinity(
                task,
                match_fields=[
                    {
                        'key': 'metadata.name',
                        'operator': 'In',
                        'values': ['node-1', 'node-2'],
                    }
                ],
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'nodeAffinity': [
                    {
                        'matchFields': [
                            {
                                'key': 'metadata.name',
                                'operator': 'In',
                                'values': ['node-1', 'node-2'],
                            }
                        ]
                    }
                ]
            }
        }

    def test_add_preferred_scheduling_with_weight(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.add_node_affinity(
                task,
                match_expressions=[
                    {'key': 'zone', 'operator': 'In', 'values': ['us-west-1']}
                ],
                weight=100,
            )

        expression = {
            'key': 'zone',
            'operator': 'In',
            'values': ['us-west-1'],
        }
        assert recorded(my_pipeline) == {
            'exec-comp': {
                'nodeAffinity': [
                    {'matchExpressions': [expression], 'weight': 100}
                ]
            }
        }
        assert lowered(my_pipeline)['comp']['affinity'] == {
            'nodeAffinity': {
                'preferredDuringSchedulingIgnoredDuringExecution': [
                    {
                        'weight': 100,
                        'preference': {'matchExpressions': [expression]},
                    }
                ]
            }
        }

    def test_add_combined_match_expressions_and_fields(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.add_node_affinity(
                task,
                match_expressions=[
                    {'key': 'disktype', 'operator': 'In', 'values': ['ssd']},
                    {'key': 'gpu', 'operator': 'Exists'},
                ],
                match_fields=[
                    {
                        'key': 'metadata.name',
                        'operator': 'NotIn',
                        'values': ['node-5', 'node-6'],
                    }
                ],
            )

        term = {
            'matchExpressions': [
                {'key': 'disktype', 'operator': 'In', 'values': ['ssd']},
                {'key': 'gpu', 'operator': 'Exists'},
            ],
            'matchFields': [
                {
                    'key': 'metadata.name',
                    'operator': 'NotIn',
                    'values': ['node-5', 'node-6'],
                }
            ],
        }
        assert recorded(my_pipeline) == {'exec-comp': {'nodeAffinity': [term]}}
        assert lowered(my_pipeline)['comp']['affinity']['nodeAffinity'][
            'requiredDuringSchedulingIgnoredDuringExecution'
        ]['nodeSelectorTerms'] == [term]

    def test_add_multiple_node_affinity_terms(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.add_node_affinity(
                task,
                match_expressions=[
                    {'key': 'disktype', 'operator': 'In', 'values': ['ssd']}
                ],
            )
            kubernetes.add_node_affinity(
                task,
                match_fields=[
                    {
                        'key': 'metadata.name',
                        'operator': 'In',
                        'values': ['node-1'],
                    }
                ],
            )

        terms = [
            {
                'matchExpressions': [
                    {'key': 'disktype', 'operator': 'In', 'values': ['ssd']}
                ]
            },
            {
                'matchFields': [
                    {
                        'key': 'metadata.name',
                        'operator': 'In',
                        'values': ['node-1'],
                    }
                ]
            },
        ]
        assert recorded(my_pipeline) == {'exec-comp': {'nodeAffinity': terms}}
        assert (
            lowered(my_pipeline)['comp']['affinity']['nodeAffinity'][
                'requiredDuringSchedulingIgnoredDuringExecution'
            ]['nodeSelectorTerms']
            == terms
        )

    def test_respects_other_configuration(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.use_secret_as_volume(
                task, secret_name='my-secret', mount_path='/mnt/my_vol'
            )
            kubernetes.add_node_affinity(
                task,
                match_expressions=[
                    {'key': 'disktype', 'operator': 'In', 'values': ['ssd']}
                ],
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'nodeAffinity': [
                    {
                        'matchExpressions': [
                            {
                                'key': 'disktype',
                                'operator': 'In',
                                'values': ['ssd'],
                            }
                        ]
                    }
                ],
                'secretAsVolume': [
                    secret_as_volume('my-secret', '/mnt/my_vol')
                ],
            }
        }

    def test_invalid_match_expression_missing_key(self):
        with pytest.raises(ValueError, match="non-empty 'key'"):

            @dsl.pipeline
            def my_pipeline():
                kubernetes.add_node_affinity(
                    comp(),
                    match_expressions=[{'operator': 'In', 'values': ['ssd']}],
                )

    def test_invalid_match_expression_missing_operator(self):
        with pytest.raises(ValueError, match="non-empty 'operator'"):

            @dsl.pipeline
            def my_pipeline():
                kubernetes.add_node_affinity(
                    comp(),
                    match_expressions=[{'key': 'disktype', 'values': ['ssd']}],
                )

    def test_invalid_match_expression_invalid_operator(self):
        with pytest.raises(ValueError, match='Invalid operator'):

            @dsl.pipeline
            def my_pipeline():
                kubernetes.add_node_affinity(
                    comp(),
                    match_expressions=[
                        {
                            'key': 'disktype',
                            'operator': 'INVALID',
                            'values': ['ssd'],
                        }
                    ],
                )

    @pytest.mark.parametrize('weight', [0, 101])
    def test_invalid_weight(self, weight):
        with pytest.raises(
            ValueError, match='weight must be between 1 and 100'
        ):

            @dsl.pipeline
            def my_pipeline():
                kubernetes.add_node_affinity(
                    comp(),
                    match_expressions=[
                        {'key': 'disktype', 'operator': 'In', 'values': ['ssd']}
                    ],
                    weight=weight,
                )

    @pytest.mark.parametrize('field', ['match_expressions', 'match_fields'])
    @pytest.mark.parametrize('bad_values', ['prod', ''])
    def test_string_values_raises_type_error(self, field, bad_values):
        """A plain string for values is rejected rather than split into
        characters."""
        with pytest.raises(TypeError, match='must be a list of strings'):

            @dsl.pipeline
            def my_pipeline():
                kubernetes.add_node_affinity(
                    comp(),
                    **{
                        field: [
                            {
                                'key': 'env',
                                'operator': 'In',
                                'values': bad_values,
                            }
                        ]
                    },
                )

    @pytest.mark.parametrize('field', ['match_expressions', 'match_fields'])
    def test_list_values_still_work(self, field):
        @dsl.pipeline
        def my_pipeline():
            kubernetes.add_node_affinity(
                comp(),
                **{
                    field: [
                        {'key': 'env', 'operator': 'In', 'values': ['prod']}
                    ]
                },
            )

        key = (
            'matchExpressions'
            if field == 'match_expressions'
            else 'matchFields'
        )
        term = recorded(my_pipeline)['exec-comp']['nodeAffinity'][0]
        assert term[key][0]['values'] == ['prod']

    @pytest.mark.parametrize('field', ['match_expressions', 'match_fields'])
    @pytest.mark.parametrize('operator', ['Exists', 'DoesNotExist'])
    @pytest.mark.parametrize('extra', [{}, {'values': []}])
    def test_omitted_or_empty_values_still_work(self, field, operator, extra):
        @dsl.pipeline
        def my_pipeline():
            kubernetes.add_node_affinity(
                comp(),
                **{field: [{'key': 'env', 'operator': operator, **extra}]},
            )

        key = (
            'matchExpressions'
            if field == 'match_expressions'
            else 'matchFields'
        )
        assert recorded(my_pipeline)['exec-comp']['nodeAffinity'] == [
            {key: [{'key': 'env', 'operator': operator}]}
        ]
        assert lowered(my_pipeline)['comp']['affinity']['nodeAffinity'][
            'requiredDuringSchedulingIgnoredDuringExecution'
        ]['nodeSelectorTerms'] == [
            {key: [{'key': 'env', 'operator': operator}]}
        ]


class TestNodeAffinityJSON:
    def test_component_pipeline_input_required_scheduling(self):
        @dsl.pipeline
        def my_pipeline(affinity_input: dict):
            task = comp()
            kubernetes.add_node_affinity_json(
                task, node_affinity_json=affinity_input
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'nodeAffinity': [
                    {'nodeAffinityJson': pipeline_input('affinity_input')}
                ]
            }
        }
        template = lowered(my_pipeline)['comp']
        assert 'affinity' not in template
        assert 'nodeAffinity' in template['podSpecPatch']

    def test_component_pipeline_input_multiple_tasks(self):
        @dsl.pipeline
        def my_pipeline(affinity_input_1: dict, affinity_input_2: dict):
            t1 = comp()
            kubernetes.add_node_affinity_json(
                t1, node_affinity_json=affinity_input_1
            )
            t2 = comp()
            kubernetes.add_node_affinity_json(
                t2, node_affinity_json=affinity_input_2
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'nodeAffinity': [
                    {'nodeAffinityJson': pipeline_input('affinity_input_1')}
                ]
            },
            'exec-comp-2': {
                'nodeAffinity': [
                    {'nodeAffinityJson': pipeline_input('affinity_input_2')}
                ]
            },
        }

    def test_component_upstream_input(self):
        @dsl.pipeline
        def my_pipeline():
            upstream_task = comp_with_output()
            task = comp()
            kubernetes.add_node_affinity_json(
                task, node_affinity_json=upstream_task.output
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'nodeAffinity': [
                    {'nodeAffinityJson': task_output('comp-with-output')}
                ]
            }
        }

    def test_overwrite_previous_json(self):
        @dsl.pipeline
        def my_pipeline(affinity_input_1: dict, affinity_input_2: dict):
            task = comp()
            kubernetes.add_node_affinity_json(
                task, node_affinity_json=affinity_input_1
            )
            kubernetes.add_node_affinity_json(
                task, node_affinity_json=affinity_input_2
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'nodeAffinity': [
                    {'nodeAffinityJson': pipeline_input('affinity_input_2')}
                ]
            }
        }

    def test_static_json_lowers_to_the_pod_affinity(self):
        """A literal NodeAffinity document is validated against the Kubernetes
        model and lowered as given."""
        affinity = {
            'requiredDuringSchedulingIgnoredDuringExecution': {
                'nodeSelectorTerms': [
                    {
                        'matchExpressions': [
                            {
                                'key': 'disktype',
                                'operator': 'In',
                                'values': ['ssd'],
                            }
                        ]
                    }
                ]
            }
        }

        @dsl.pipeline
        def my_pipeline():
            kubernetes.add_node_affinity_json(
                comp(), node_affinity_json=affinity
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'nodeAffinity': [
                    {
                        'nodeAffinityJson': {
                            'runtimeValue': {'constant': affinity}
                        }
                    }
                ]
            }
        }
        assert lowered(my_pipeline)['comp']['affinity'] == {
            'nodeAffinity': affinity
        }

    def test_mixed_explicit_and_json(self):
        @dsl.pipeline
        def my_pipeline(affinity_input: dict):
            task = comp()
            kubernetes.add_node_affinity(
                task,
                match_expressions=[
                    {'key': 'disktype', 'operator': 'In', 'values': ['ssd']}
                ],
            )
            kubernetes.add_node_affinity_json(
                task, node_affinity_json=affinity_input
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'nodeAffinity': [
                    {
                        'matchExpressions': [
                            {
                                'key': 'disktype',
                                'operator': 'In',
                                'values': ['ssd'],
                            }
                        ]
                    },
                    {'nodeAffinityJson': pipeline_input('affinity_input')},
                ]
            }
        }

    def test_invalid_node_affinity_json(self):
        with pytest.raises(ValueError, match='Invalid V1NodeAffinity JSON'):

            @dsl.pipeline
            def my_pipeline():
                kubernetes.add_node_affinity_json(
                    comp(), node_affinity_json={'foo': 'bar'}
                )
