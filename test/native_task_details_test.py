# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0

import base64
import gzip
import json
from unittest.mock import Mock

import kfp
import pytest
from kfp import server_api
from kfp.client._native import NativeBackend


@pytest.mark.parametrize('compressed', [False, True])
def test_get_run_retains_typed_tasks_and_cached_artifact_origin(compressed):
    identity = {
        'schema': 'kfp-argo/v1',
        'port': 'data',
        'type': 'system.Dataset@0.0.1',
        'uri': 's3://bucket/original/data',
        'metadata': {'rows': 3},
        'producer': {
            'run': 'original-run',
            'task': 'original-pod',
            'namespace': 'team',
        },
    }
    workflow = {
        'metadata': {'name': 'wf', 'uid': 'run-id', 'namespace': 'team'},
        'spec': {
            'templates': [
                {
                    'name': 'component',
                    'metadata': {
                        'annotations': {
                            'pipelines.kubeflow.org/input-parameter-types': json.dumps(
                                {'text': 'String'}
                            ),
                            'pipelines.kubeflow.org/output-parameter-types': json.dumps(
                                {'count': 'Integer', 'label': 'String'}
                            ),
                        }
                    },
                    'container': {'image': 'test'},
                }
            ]
        },
        'status': {
            'phase': 'Succeeded',
            'nodes': {
                'wf': {
                    'id': 'wf',
                    'name': 'wf',
                    'displayName': 'wf',
                    'type': 'DAG',
                    'phase': 'Succeeded',
                },
                'task': {
                    'id': 'task',
                    'name': 'wf.produce',
                    'displayName': 'produce',
                    'templateName': 'component',
                    'type': 'Pod',
                    'phase': 'Succeeded',
                    'boundaryID': 'wf',
                    'memoizationStatus': {'hit': True, 'key': 'fingerprint'},
                    'inputs': {
                        'parameters': [
                            {'name': 'text', 'value': '3'},
                            {'name': 'kfp-config-0', 'value': 'private'},
                        ]
                    },
                    'outputs': {
                        'parameters': [
                            {'name': 'count', 'value': '3'},
                            {'name': 'label', 'value': '3'},
                            {
                                'name': 'kfp-meta-data',
                                'value': json.dumps(identity),
                            },
                        ]
                    },
                },
            },
        },
    }
    if compressed:
        content = json.dumps(workflow['status'].pop('nodes')).encode()
        workflow['status']['compressedNodes'] = base64.b64encode(
            gzip.compress(content)
        ).decode()
        workflow['status']['nodes'] = {}
    backend = NativeBackend(server_api.Configuration(), lambda: 'team')
    backend._workflow = Mock(return_value=(workflow, True))
    backend._run_states = Mock(return_value={})
    client = object.__new__(kfp.Client)
    client._run_api = backend
    run = client.get_run('run-id')
    assert run.task_count == 2
    task = next(t for t in run.tasks if t.display_name == 'produce')
    assert task.state == 'CACHED'
    assert task.pods == []
    assert task.parent_task_id == 'wf'
    assert [(p.parameter_key, p.value) for p in task.inputs.parameters] == [
        ('text', '3')
    ]
    assert {p.parameter_key: p.value for p in task.outputs.parameters} == {
        'count': 3,
        'label': '3',
    }
    artifact = task.outputs.artifacts[0].artifacts[0]
    assert artifact.uri == identity['uri']
    assert artifact.metadata == {'rows': 3}
    assert artifact.artifact_id.startswith('original-run/')


@pytest.mark.parametrize('nodes', [None, {}])
def test_offloaded_tasks_are_not_reported_as_an_empty_completed_inventory(
    nodes,
):
    backend = NativeBackend(server_api.Configuration(), lambda: 'team')
    run = backend._run(
        {
            'metadata': {'name': 'wf', 'uid': 'run-id', 'namespace': 'team'},
            'spec': {},
            'status': {
                'phase': 'Succeeded',
                'nodes': nodes,
                'offloadNodeStatusVersion': 'version',
            },
        }
    )
    assert run.tasks is None
    assert run.task_count is None


def test_compressed_node_status_is_bounded_and_requires_an_object(monkeypatch):
    from kfp.client import _task_details

    monkeypatch.setattr(_task_details, 'MAX_NODE_STATUS_BYTES', 256)

    def resource(value):
        return {
            'status': {
                'nodes': {},
                'compressedNodes': base64.b64encode(
                    gzip.compress(json.dumps(value).encode())
                ).decode(),
            }
        }

    with pytest.raises(
        ValueError, match='Expanded workflow node status exceeds'
    ):
        _task_details.node_status(resource({'padding': 'x' * 512}))
    with pytest.raises(ValueError, match='must be an object'):
        _task_details.node_status(resource([]))


def test_retry_wrappers_keep_their_real_execution_pods():
    from kfp.client._task_details import tasks

    workflow = {
        'metadata': {'name': 'wf', 'uid': 'run-id', 'namespace': 'team'},
        'spec': {
            'templates': [
                {
                    'name': 'component',
                    'metadata': {
                        'annotations': {
                            'pipelines.kubeflow.org/component-wrapper': 'true'
                        }
                    },
                }
            ]
        },
        'status': {
            'nodes': {
                'wf': {
                    'id': 'wf',
                    'name': 'wf',
                    'type': 'DAG',
                    'phase': 'Failed',
                },
                'retry': {
                    'id': 'retry',
                    'name': 'wf.task',
                    'displayName': 'task',
                    'type': 'Retry',
                    'phase': 'Failed',
                    'boundaryID': 'wf',
                    'children': ['wrapper'],
                    'templateName': 'component',
                },
                'wrapper': {
                    'id': 'wrapper',
                    'name': 'wf.task(0)',
                    'type': 'DAG',
                    'phase': 'Failed',
                    'boundaryID': 'wf',
                    'templateName': 'component',
                },
                'pod': {
                    'id': 'pod',
                    'name': 'wf.task(0).execute',
                    'type': 'Pod',
                    'phase': 'Failed',
                    'boundaryID': 'wrapper',
                    'podName': 'real-pod',
                    'message': 'bad output',
                },
            }
        },
    }
    result = tasks(workflow)
    assert [task.task_id for task in result] == ['wf', 'retry']
    task = result[1]
    assert [pod.name for pod in task.pods] == ['real-pod']
    assert task.lifecycle_message == 'bad output'


def test_alternative_compression_is_unavailable_not_an_empty_inventory():
    from kfp.client._task_details import tasks

    assert (
        tasks(
            {
                'status': {
                    'nodes': {},
                    'compressedNodes': base64.b64encode(b'not-gzip').decode(),
                }
            }
        )
        is None
    )


def test_task_fields_derived_from_argo_status_match_stock_semantics():
    """Fields the inventory listed as unpopulated (C19, U53, U54) that Argo can
    supply: state history, scope path, iteration attributes, lifecycle
    classification, pod UIDs, artifact creation times and input producers."""
    identity = {
        'schema': 'kfp-argo/v1',
        'port': 'data',
        'type': 'system.Dataset@0.0.1',
        'uri': 's3://bucket/data',
        'metadata': {},
        'producer': {
            'run': 'run-id',
            'task': 'wf-print-1',
            'namespace': 'team',
        },
    }
    workflow = {
        'metadata': {
            'name': 'wf',
            'uid': 'run-id',
            'namespace': 'team',
            'creationTimestamp': '2026-01-01T00:00:00Z',
            'annotations': {
                'workflows.argoproj.io/scheduled-time': '2026-01-01T00:00:05Z'
            },
        },
        'spec': {
            'templates': [{'name': 'component', 'container': {'image': 'test'}}]
        },
        'status': {
            'phase': 'Failed',
            'startedAt': '2026-01-01T00:00:10Z',
            'finishedAt': '2026-01-01T00:01:00Z',
            'nodes': {
                'wf': {
                    'id': 'wf',
                    'name': 'wf',
                    'displayName': 'wf',
                    'type': 'DAG',
                    'phase': 'Failed',
                    'startedAt': '2026-01-01T00:00:10Z',
                    'finishedAt': '2026-01-01T00:01:00Z',
                    'children': ['loop', 'user', 'pending', 'cached'],
                },
                'loop': {
                    'id': 'loop',
                    'name': 'wf.for-loop-1',
                    'displayName': 'for-loop-1',
                    'type': 'TaskGroup',
                    'phase': 'Failed',
                    'boundaryID': 'wf',
                    'startedAt': '2026-01-01T00:00:10Z',
                    'finishedAt': '2026-01-01T00:00:40Z',
                    'children': ['iter0', 'iter1'],
                },
                'iter0': {
                    'id': 'iter0',
                    'name': 'wf.for-loop-1(0:a)',
                    'displayName': 'for-loop-1(0:a)',
                    'templateName': 'component',
                    'type': 'Pod',
                    'podName': 'wf-print-1',
                    'phase': 'Succeeded',
                    'boundaryID': 'wf',
                    'startedAt': '2026-01-01T00:00:10Z',
                    'finishedAt': '2026-01-01T00:00:20Z',
                    'outputs': {
                        'parameters': [
                            {
                                'name': 'kfp-meta-data',
                                'value': json.dumps(identity),
                            }
                        ]
                    },
                },
                'iter1': {
                    'id': 'iter1',
                    'name': 'wf.for-loop-1(1:b)',
                    'displayName': 'for-loop-1(1:b)',
                    'templateName': 'component',
                    'type': 'Pod',
                    'podName': 'wf-print-2',
                    'phase': 'Failed',
                    'message': 'main: OOMKilled (exit code 137)',
                    'boundaryID': 'wf',
                    'startedAt': '2026-01-01T00:00:10Z',
                    'finishedAt': '2026-01-01T00:00:40Z',
                    'inputs': {
                        'parameters': [
                            {
                                'name': 'kfp-meta-data',
                                'value': json.dumps(identity),
                            }
                        ]
                    },
                },
                'user': {
                    'id': 'user',
                    'name': 'wf.user',
                    'displayName': 'user',
                    'templateName': 'component',
                    'type': 'Pod',
                    'phase': 'Failed',
                    'message': 'Error (exit code 1)',
                    'boundaryID': 'wf',
                    'startedAt': '2026-01-01T00:00:10Z',
                    'finishedAt': '2026-01-01T00:00:30Z',
                },
                'pending': {
                    'id': 'pending',
                    'name': 'wf.pending',
                    'displayName': 'pending',
                    'templateName': 'component',
                    'type': 'Pod',
                    'phase': 'Pending',
                    'message': 'ContainerCreating',
                    'boundaryID': 'wf',
                    'startedAt': '2026-01-01T00:00:50Z',
                },
                'cached': {
                    'id': 'cached',
                    'name': 'wf.cached',
                    'displayName': 'cached',
                    'templateName': 'component',
                    'type': 'Pod',
                    'phase': 'Succeeded',
                    'boundaryID': 'wf',
                    'memoizationStatus': {'hit': True, 'key': 'k'},
                    'startedAt': '2026-01-01T00:00:10Z',
                    'finishedAt': '2026-01-01T00:00:10Z',
                },
            },
        },
    }
    backend = NativeBackend(server_api.Configuration(), lambda: 'team')
    backend._workflow = Mock(return_value=(workflow, True))
    backend._run_states = Mock(return_value={})
    backend._pod_uids = Mock(return_value={'wf-print-1': 'pod-uid-1'})
    client = object.__new__(kfp.Client)
    client._run_api = backend
    run = client.get_run('run-id')
    backend._pod_uids.assert_called_once_with(workflow)

    assert [
        (s.state, s.update_time.isoformat()) for s in run.state_history
    ] == [
        ('PENDING', '2026-01-01T00:00:00+00:00'),
        ('RUNNING', '2026-01-01T00:00:10+00:00'),
        ('FAILED', '2026-01-01T00:01:00+00:00'),
    ]
    assert run.scheduled_at.isoformat() == '2026-01-01T00:00:05+00:00'

    tasks = {task.task_id: task for task in run.tasks}
    assert tasks['wf'].scope_path == 'root'
    assert tasks['loop'].scope_path == 'root.for-loop-1'
    assert tasks['iter0'].scope_path == 'root.for-loop-1.for-loop-1(0:a)'
    assert tasks['loop'].type_attributes.iteration_count == '2'
    assert tasks['iter0'].type_attributes.iteration_index == '0'
    assert tasks['iter1'].type_attributes.iteration_index == '1'
    assert tasks['user'].type_attributes is None

    assert [(s.state) for s in tasks['iter0'].state_history] == [
        'RUNNING',
        'SUCCEEDED',
    ]
    assert tasks['iter0'].state_history[1].update_time.isoformat() == (
        '2026-01-01T00:00:20+00:00'
    )
    assert [s.state for s in tasks['pending'].state_history] == ['RUNNING']
    assert [s.state for s in tasks['cached'].state_history] == ['CACHED']

    assert tasks['iter0'].pods[0].uid == 'pod-uid-1'
    assert tasks['iter1'].pods[0].uid is None

    assert tasks['iter1'].lifecycle_message == 'main: OOMKilled (exit code 137)'
    assert tasks['iter1'].lifecycle_category == 'runtime'
    # User-script exits and transient startup reasons are not lifecycle failures
    # (stock drops them from lifecycle_message); the raw text stays in status.
    assert tasks['user'].lifecycle_message is None
    assert tasks['user'].lifecycle_category is None
    assert tasks['user'].status_metadata.message == 'Error (exit code 1)'
    assert tasks['pending'].lifecycle_message is None

    output = tasks['iter0'].outputs.artifacts[0]
    assert output.producer is None
    assert (
        output.artifacts[0].created_at.isoformat()
        == '2026-01-01T00:00:20+00:00'
    )
    consumed = tasks['iter1'].inputs.artifacts[0]
    assert consumed.producer.task_name == 'wf-print-1'
    # An input was created when its producer finished, not when it was consumed.
    assert (
        consumed.artifacts[0].created_at.isoformat()
        == '2026-01-01T00:00:20+00:00'
    )


@pytest.mark.parametrize(
    'message, category',
    [
        ('ErrImagePull: rpc error', 'image-pull'),
        ('Back-off pulling image "x"', 'image-pull'),
        ('pods "p" is forbidden: exceeded quota', 'admission'),
        ('Forbidden', 'admission'),
        ('kyverno: policy violation', 'admission'),
        ('0/3 nodes are available: Insufficient cpu.', 'scheduling'),
        ('Unschedulable', 'scheduling'),
        ('main: OOMKilled (exit code 137)', 'runtime'),
        ('CrashLoopBackOff', 'runtime'),
        ('Error', 'runtime'),
        ('Error (exit code 2): is forbidden in stderr', 'unknown'),
        ('main: Error (exit code 2)', 'unknown'),
        ('something else entirely', 'unknown'),
        ('', None),
    ],
)
def test_lifecycle_category_matches_stock_classifier(message, category):
    from kfp.client._task_details import lifecycle_category

    assert lifecycle_category(message) == category
