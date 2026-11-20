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
