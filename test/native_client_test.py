# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Exercise the stock Client facade at its native HTTP boundary."""

import copy
import json
from urllib.parse import unquote, urlsplit
from uuid import uuid4

import kfp
import pytest
import requests
from kfp import dsl, server_api


@dsl.component
def echo(value: str) -> str:
    return value


@dsl.pipeline(name='stock-client-program')
def stock_program(value: str = 'hello'):
    echo(value=value)


REPOSITORIES = {
    'apiVersion': 'v1',
    'kind': 'ConfigMap',
    'metadata': {
        'name': 'artifact-repositories',
        'namespace': 'team',
        'uid': 'repositories-uid',
        'resourceVersion': '1',
        'annotations': {
            'workflows.argoproj.io/default-artifact-repository': 'default-v1'
        },
    },
    'data': {
        'default-v1': 's3:\n  bucket: argo-artifacts\n  endpoint: minio:9000\n',
        'archive': 's3:\n  bucket: cold-storage\n  endpoint: minio:9000\n',
        'gcs-exports': 'gcs:\n  bucket: exports\n',
    },
}


@pytest.fixture
def native_store():
    return {
        # Argo's namespace artifact repositories, which runs bind to at submit.
        'maps': {'artifact-repositories': copy.deepcopy(REPOSITORIES)},
        'workflows': {},
        'archives': {},
        'versions': {},
        'schedules': {},
    }


@pytest.fixture
def native_api(monkeypatch, tmp_path, native_store):
    monkeypatch.setattr(
        kfp.Client, '_LOCAL_KFP_CONTEXT', str(tmp_path / 'context.json')
    )
    requests_seen = []
    resources = native_store['maps']
    workflows = native_store['workflows']
    archives = native_store['archives']
    versions = native_store['versions']
    schedules = native_store['schedules']

    def request(session, method, url, **kwargs):
        path = urlsplit(url).path.removeprefix('/pipeline')
        requests_seen.append((method, path, kwargs))
        assert path.startswith(('/argo/', '/kubernetes/')), path
        assert kwargs['headers']['Authorization'] == 'Bearer test-token'
        assert kwargs['allow_redirects'] is False
        status, body = 200, {}
        if path == '/argo/api/v1/info':
            body = {'managedNamespace': 'team'}
        elif path == '/argo/api/v1/workflows/team' and method == 'POST':
            body = kwargs['json']['workflow']
            body['metadata'].update(
                uid=str(uuid4()),
                name=f'submitted-run-{len(workflows)}',
                namespace='team',
                creationTimestamp='2026-01-01T00:00:00Z',
            )
            body['status'] = {'phase': 'Pending'}
            workflows[body['metadata']['uid']] = body
            status = 201
        elif (
            path
            == '/kubernetes/apis/argoproj.io/v1alpha1/namespaces/team/workflows'
        ):
            body = {
                'items': [
                    {'metadata': item['metadata']}
                    for item in workflows.values()
                ]
                if 'PartialObjectMetadataList' in kwargs['headers']['Accept']
                else list(workflows.values())
            }
        elif path == '/argo/api/v1/archived-workflows':
            body = {'items': list(archives.values())}
        elif path.startswith('/argo/api/v1/archived-workflows/'):
            uid = path.rsplit('/', 1)[1]
            if uid not in archives:
                status = 404
            elif method == 'DELETE':
                del archives[uid]
            else:
                body = archives[uid]
        elif path.startswith('/argo/api/v1/workflows/team/'):
            parts = path.removeprefix('/argo/api/v1/workflows/team/').split('/')
            found = next(
                (
                    item
                    for item in workflows.values()
                    if item['metadata']['name'] == parts[0]
                ),
                None,
            )
            if found is None:
                status = 404
            elif (
                len(parts) == 2 and parts[1] == 'terminate' and method == 'PUT'
            ):
                found['spec']['shutdown'] = 'Terminate'
            else:
                body = found
        elif (
            path.startswith(
                '/kubernetes/apis/argoproj.io/v1alpha1/namespaces/team/workflows/'
            )
            and method == 'DELETE'
        ):
            name = path.rsplit('/', 1)[1]
            uid = kwargs['json']['preconditions']['uid']
            if (
                uid not in workflows
                or workflows[uid]['metadata']['name'] != name
            ):
                status = 409
            else:
                del workflows[uid]
        elif path == '/argo/api/v1/cron-workflows/team':
            if method == 'GET':
                body = {'items': list(schedules.values())}
            elif method == 'POST':
                body = kwargs['json']['cronWorkflow']
                body['metadata'].update(
                    uid=str(uuid4()),
                    namespace='team',
                    resourceVersion='1',
                    creationTimestamp='2026-01-01T00:00:00Z',
                )
                schedules[body['metadata']['name']] = body
                status = 201
        elif path.startswith('/argo/api/v1/cron-workflows/team/'):
            name = path.rsplit('/', 1)[1]
            if name not in schedules:
                status = 404
            elif method == 'PUT':
                body = kwargs['json']['cronWorkflow']
                assert (
                    body['metadata']['resourceVersion']
                    == schedules[name]['metadata']['resourceVersion']
                )
                schedules[name] = body
            else:
                body = schedules[name]
        elif (
            path.startswith(
                '/kubernetes/apis/argoproj.io/v1alpha1/namespaces/team/cronworkflows/'
            )
            and method == 'DELETE'
        ):
            name = path.rsplit('/', 1)[1]
            assert (
                kwargs['json']['preconditions']['uid']
                == schedules[name]['metadata']['uid']
            )
            assert kwargs['json']['propagationPolicy'] == 'Orphan'
            del schedules[name]
        elif path == '/argo/api/v1/workflow-templates/team':
            if method == 'GET':
                body = {'items': list(versions.values())}
            elif method == 'POST':
                body = kwargs['json']['template']
                body['metadata'].update(
                    uid=str(uuid4()),
                    namespace='team',
                    creationTimestamp=f'2026-01-01T00:00:{len(versions):02d}Z',
                )
                versions[body['metadata']['name']] = body
                status = 201
        elif path.startswith(
            '/kubernetes/apis/argoproj.io/v1alpha1/namespaces/team/workflowtemplates/'
        ):
            name = unquote(path.rsplit('/', 1)[1])
            if name not in versions:
                status = 404
            elif method == 'DELETE':
                assert (
                    kwargs['json']['preconditions']['uid']
                    == versions[name]['metadata']['uid']
                )
                assert kwargs['json']['propagationPolicy'] == 'Orphan'
                del versions[name]
        elif path == '/kubernetes/api/v1/namespaces/team/configmaps':
            if method == 'GET':
                selector = kwargs.get('params', {}).get('labelSelector', '')
                key, _, value = selector.partition('=')
                body = {
                    'items': [
                        item
                        for item in resources.values()
                        if not selector
                        or item['metadata'].get('labels', {}).get(key) == value
                    ],
                    'metadata': {},
                }
            elif method == 'POST':
                body = kwargs['json']
                name = body['metadata']['name']
                if name in resources:
                    status = 409
                else:
                    body['metadata'].update(
                        uid=str(uuid4()),
                        namespace='team',
                        resourceVersion='1',
                        creationTimestamp='2026-01-01T00:00:00Z',
                    )
                    resources[name] = body
                    status = 201
        elif path.startswith('/kubernetes/api/v1/namespaces/team/configmaps/'):
            name = unquote(path.rsplit('/', 1)[1])
            if name not in resources:
                status = 404
            elif method == 'GET':
                body = resources[name]
            elif method == 'PUT':
                body = kwargs['json']
                assert (
                    body['metadata']['resourceVersion']
                    == resources[name]['metadata']['resourceVersion']
                )
                resources[name] = body
            elif method == 'DELETE':
                assert (
                    kwargs['json']['preconditions']['uid']
                    == resources[name]['metadata']['uid']
                )
                del resources[name]
        else:
            status = 404
        response = requests.Response()
        response.status_code = status
        response.reason = 'OK' if status < 400 else 'Request rejected'
        response._content = json.dumps(body).encode()
        return response

    monkeypatch.setattr(requests.Session, 'request', request)
    client = kfp.Client(
        host='https://native.invalid/pipeline',
        namespace='team',
        existing_token='test-token',
    )
    return client, resources, requests_seen


def test_unchanged_experiment_lifecycle_and_response_types(native_api):
    client, resources, requests_seen = native_api
    experiment = client.create_experiment(
        'Training', description='User description'
    )
    assert isinstance(experiment, server_api.V2Experiment)
    assert experiment.display_name == 'Training'
    assert experiment.description == 'User description'
    assert experiment.namespace == 'team'
    assert experiment.created_at.year == 2026
    assert (
        client.create_experiment('Training').experiment_id
        == experiment.experiment_id
    )
    # One experiment ConfigMap beside the namespace artifact repositories.
    assert (
        sum(1 for item in resources.values() if item['metadata'].get('labels'))
        == 1
    )
    assert (
        client.get_experiment(experiment_id=experiment.experiment_id).to_dict()
        == experiment.to_dict()
    )
    assert (
        client.get_experiment(experiment_name='Training').experiment_id
        == experiment.experiment_id
    )
    listing = client.list_experiments()
    assert isinstance(listing, server_api.V2ListExperimentsResponse)
    assert listing.total_size == 1
    assert listing.experiments[0].experiment_id == experiment.experiment_id
    assert client.archive_experiment(experiment.experiment_id) == {}
    assert (
        client.get_experiment(
            experiment_id=experiment.experiment_id
        ).storage_state
        == 'ARCHIVED'
    )
    assert client.unarchive_experiment(experiment.experiment_id) == {}
    assert (
        client.get_experiment(
            experiment_id=experiment.experiment_id
        ).storage_state
        == 'AVAILABLE'
    )
    assert client.delete_experiment(experiment.experiment_id) == {}
    assert set(resources) == {'artifact-repositories'}
    assert all('/apis/v2' not in path for _, path, _ in requests_seen)


@pytest.fixture
def archive_fixture(native_api, native_store):
    client, resources, requests_seen = native_api
    experiment = client.create_experiment('Archive cascade')
    experiment_id = experiment.experiment_id
    for uid, owner, phase in [
        ('running', experiment_id, 'Running'),
        ('finished', experiment_id, 'Succeeded'),
        ('unrelated', 'someone-else', 'Running'),
    ]:
        native_store['workflows'][uid] = {
            'metadata': {
                'uid': uid,
                'name': uid,
                'namespace': 'team',
                'labels': {
                    'pipelines.kubeflow.org/pipeline': 'test',
                    'pipelines.kubeflow.org/experiment': owner,
                },
            },
            'spec': {},
            'status': {'phase': phase},
        }
    archived = {
        'metadata': {
            'uid': 'sql-only',
            'name': 'sql-only',
            'namespace': 'team',
            'labels': {
                'pipelines.kubeflow.org/pipeline': 'test',
                'pipelines.kubeflow.org/experiment': experiment_id,
            },
        },
        'spec': {},
        'status': {'phase': 'Succeeded'},
    }
    native_store['archives']['sql-only'] = archived
    for name, owner in [
        ('scheduled', experiment_id),
        ('unrelated-schedule', 'someone-else'),
    ]:
        native_store['schedules'][name] = {
            'metadata': {
                'uid': name,
                'name': name,
                'namespace': 'team',
                'resourceVersion': '1',
            },
            'spec': {
                'suspend': False,
                'workflowMetadata': {
                    'labels': {'pipelines.kubeflow.org/experiment': owner}
                },
            },
        }
    requests_seen.clear()
    return client, experiment_id, resources, requests_seen


def test_experiment_archive_cascades_without_terminating_or_restoring_children(
    archive_fixture, native_store
):
    client, experiment_id, resources, requests_seen = archive_fixture
    client.archive_experiment(experiment_id)
    assert native_store['schedules']['scheduled']['spec']['suspend'] is True
    assert (
        native_store['schedules']['unrelated-schedule']['spec']['suspend']
        is False
    )
    for uid in ['running', 'finished', 'sql-only']:
        assert resources['run-' + uid]['data']['storageState'] == 'ARCHIVED'
    assert 'run-unrelated' not in resources
    assert native_store['workflows']['running']['status']['phase'] == 'Running'
    assert native_store['workflows']['running']['spec'] == {}
    assert not any(
        method == 'DELETE' or path.endswith('/terminate')
        for method, path, _ in requests_seen
    )
    mutations = [
        (method, path)
        for method, path, _ in requests_seen
        if method in ['PUT', 'POST']
    ]
    assert '/cron-workflows/' in mutations[0][1]
    assert mutations[-1][1].endswith(
        '/'
        + next(
            name
            for name, r in resources.items()
            if r['metadata']['uid'] == experiment_id
        )
    )
    client.archive_experiment(experiment_id)
    with pytest.raises(server_api.ApiException, match='experiment first'):
        client.unarchive_run('finished')
    client.unarchive_experiment(experiment_id)
    assert native_store['schedules']['scheduled']['spec']['suspend'] is True
    assert all(
        resources['run-' + uid]['data']['storageState'] == 'ARCHIVED'
        for uid in ['running', 'finished', 'sql-only']
    )


@pytest.mark.parametrize('phase', ['listing', 'schedule', 'run-state'])
def test_experiment_archive_failure_remains_visible_and_retryable(
    archive_fixture, native_store, monkeypatch, phase
):
    client, experiment_id, resources, _ = archive_fixture
    original = requests.Session.request
    blocked = True

    def request(session, method, url, **kwargs):
        path = urlsplit(url).path
        fail = (
            (
                phase == 'listing'
                and method == 'GET'
                and path.endswith('/archived-workflows')
            )
            or (
                phase == 'schedule'
                and method == 'PUT'
                and path.endswith('/cron-workflows/team/scheduled')
            )
            or (
                phase == 'run-state'
                and method == 'POST'
                and kwargs.get('json', {}).get('metadata', {}).get('name')
                == 'run-finished'
            )
        )
        if blocked and fail:
            response = requests.Response()
            response.status_code = 403
            response.reason = 'Forbidden'
            response._content = b'{}'
            return response
        return original(session, method, url, **kwargs)

    monkeypatch.setattr(requests.Session, 'request', request)
    with pytest.raises(server_api.ApiException) as result:
        client.archive_experiment(experiment_id)
    assert result.value.status == 403
    assert (
        client.get_experiment(experiment_id=experiment_id).storage_state
        == 'AVAILABLE'
    )
    assert 'run-finished' not in resources
    if phase in ('listing', 'schedule'):
        assert (
            native_store['schedules']['scheduled']['spec']['suspend'] is False
        )
        assert 'run-running' not in resources
    else:
        assert native_store['schedules']['scheduled']['spec']['suspend'] is True
        assert resources['run-running']['data']['storageState'] == 'ARCHIVED'
    blocked = False
    client.archive_experiment(experiment_id)
    assert (
        client.get_experiment(experiment_id=experiment_id).storage_state
        == 'ARCHIVED'
    )
    assert resources['run-finished']['data']['storageState'] == 'ARCHIVED'


def test_archive_includes_runs_created_while_suspending_schedules(
    archive_fixture, native_store, monkeypatch
):
    client, experiment_id, resources, _ = archive_fixture
    original = requests.Session.request

    def request(session, method, url, **kwargs):
        response = original(session, method, url, **kwargs)
        if method == 'PUT' and urlsplit(url).path.endswith(
            '/cron-workflows/team/scheduled'
        ):
            late = json.loads(json.dumps(native_store['workflows']['running']))
            late['metadata'].update(uid='late', name='late')
            native_store['workflows']['late'] = late
        return response

    monkeypatch.setattr(requests.Session, 'request', request)
    client.archive_experiment(experiment_id)
    assert resources['run-late']['data']['storageState'] == 'ARCHIVED'
    assert native_store['workflows']['late']['status']['phase'] == 'Running'


def test_public_filtering_sorting_and_pagination(native_api):
    client, _, _ = native_api
    for name in ['B', 'C', 'A']:
        client.create_experiment(name)
    first = client.list_experiments(page_size=2, sort_by='display_name')
    assert [item.display_name for item in first.experiments] == ['A', 'B']
    assert first.next_page_token
    second = client.list_experiments(
        page_token=first.next_page_token, page_size=2, sort_by='display_name'
    )
    assert [item.display_name for item in second.experiments] == ['C']
    assert second.next_page_token == ''
    result = client.list_experiments(
        filter=json.dumps(
            {
                'predicates': [
                    {
                        'key': 'display_name',
                        'operation': 'EQUALS',
                        'stringValue': 'B',
                    }
                ]
            }
        )
    )
    assert [item.display_name for item in result.experiments] == ['B']


def test_public_missing_experiment_error_contract(native_api):
    client, _, _ = native_api
    with pytest.raises(
        ValueError, match='No experiment is found with name absent'
    ):
        client.get_experiment(experiment_name='absent')
    with pytest.raises(server_api.ApiException) as error:
        client.get_experiment(experiment_id='missing')
    assert error.value.status == 404


@pytest.mark.parametrize(
    'arguments, expected, wire',
    [
        ({}, None, 'null'),
        ({'value': 'null'}, 'null', '"null"'),
        ({'value': ''}, '', '""'),
    ],
)
def test_optional_root_none_remains_distinct_from_string_values(
    native_api, arguments, expected, wire
):
    client, resources, _ = native_api

    @dsl.component
    def optional(value: str = None) -> str:
        return 'missing' if value is None else value

    @dsl.pipeline
    def pipeline(value: str = None):
        optional(value=value)

    run = client.create_run_from_pipeline_func(pipeline, arguments=arguments)
    result = client.get_run(run.run_id)
    assert result.runtime_config.parameters == {'value': expected}
    parameter = next(
        p
        for p in result.pipeline_spec['spec']['arguments']['parameters']
        if p['name'] == 'value'
    )
    assert parameter['value'] == wire


def test_unchanged_create_run_from_pipeline_func(native_api):
    client, _, requests_seen = native_api
    result = client.create_run_from_pipeline_func(
        stock_program,
        arguments={'value': 'hello'},
        run_name='SDK run',
        namespace='team',
    )
    assert result.run_id == result.run_info.run_id
    assert isinstance(result.run_info, server_api.V2Run)
    assert result.run_info.display_name == 'SDK run'
    assert result.run_info.runtime_config.parameters == {'value': 'hello'}
    assert result.run_info.state == 'PENDING'
    submitted = [
        options['json']['workflow']
        for method, path, options in requests_seen
        if method == 'POST' and path == '/argo/api/v1/workflows/team'
    ]
    assert len(submitted) == 1
    assert submitted[0]['kind'] == 'Workflow'
    assert all(
        'memoize' in template
        for template in submitted[0]['spec']['templates']
        if 'container' in template
    )


def test_run_polling_reuses_only_the_uid_to_name_route_not_stale_data(
    native_api, native_store
):
    client, _, requests_seen = native_api
    submitted = client.create_run_from_pipeline_func(
        stock_program, arguments={'value': 'hello'}
    )
    name = submitted.run_info.pipeline_spec['metadata']['name']
    requests_seen.clear()
    assert client.get_run(submitted.run_id).state == 'PENDING'
    native_store['workflows'][submitted.run_id]['status']['phase'] = 'Succeeded'
    assert client.get_run(submitted.run_id).state == 'SUCCEEDED'
    assert not any(
        method == 'GET' and path.endswith('/workflows')
        for method, path, _ in requests_seen
    ), 'Polling must not repeatedly list every workflow specification'


def test_cold_run_lookup_lists_only_metadata_then_fetches_the_selected_run(
    native_api, native_store
):
    client, _, requests_seen = native_api
    submitted = client.create_run_from_pipeline_func(
        stock_program, arguments={'value': 'hello'}
    )
    native_store['workflows'][submitted.run_id]['status']['phase'] = 'Succeeded'
    client._run_api._known_workflows.clear()
    requests_seen.clear()
    result = client.get_run(submitted.run_id)
    assert result.state == 'SUCCEEDED'
    assert result.pipeline_spec['spec']['templates']
    listing = next(
        kwargs
        for method, path, kwargs in requests_seen
        if method == 'GET' and path.endswith('/workflows')
    )
    assert 'as=PartialObjectMetadataList' in listing['headers']['Accept']
    assert any(
        method == 'GET' and '/argo/api/v1/workflows/team/' in path
        for method, path, _ in requests_seen
    )


def test_reused_workflow_name_routes_old_uid_to_its_archive(
    native_api, native_store
):
    import copy

    client, _, _ = native_api
    submitted = client.create_run_from_pipeline_func(
        stock_program, arguments={'value': 'hello'}
    )
    name = submitted.run_info.pipeline_spec['metadata']['name']
    original = copy.deepcopy(native_store['workflows'][submitted.run_id])
    native_store['archives'][submitted.run_id] = original
    replacement = native_store['workflows'].pop(submitted.run_id)
    replacement['metadata']['uid'] = 'replacement-uid'
    native_store['workflows']['replacement-uid'] = replacement
    result = client.get_run(submitted.run_id)
    assert result.run_id == submitted.run_id
    assert (
        native_store['workflows']['replacement-uid']['metadata']['uid']
        == 'replacement-uid'
    )


def test_unchanged_pipeline_upload_version_and_submission(native_api):
    client, _, _ = native_api
    pipeline = client.upload_pipeline_from_pipeline_func(
        stock_program, pipeline_name='Pipeline name', namespace='team'
    )
    assert isinstance(pipeline, server_api.V2Pipeline)
    assert pipeline.namespace == 'team'
    assert (
        client.get_pipeline_id('Pipeline name', namespace='team')
        == pipeline.pipeline_id
    )
    version = client.upload_pipeline_version_from_pipeline_func(
        stock_program, 'Second version', pipeline_id=pipeline.pipeline_id
    )
    assert isinstance(version, server_api.V2PipelineVersion)
    assert version.pipeline_id == pipeline.pipeline_id
    assert (
        client.get_pipeline_version(
            pipeline.pipeline_id, version.pipeline_version_id
        ).pipeline_spec['kind']
        == 'WorkflowTemplate'
    )
    versions = client.list_pipeline_versions(
        pipeline.pipeline_id, sort_by='created_at desc'
    )
    assert len(versions.pipeline_versions) == 2
    assert (
        versions.pipeline_versions[0].pipeline_version_id
        == version.pipeline_version_id
    )
    experiment = client.create_experiment('Experiment')
    run = client.run_pipeline(
        experiment.experiment_id,
        'Run from version',
        pipeline_id=pipeline.pipeline_id,
        version_id=version.pipeline_version_id,
        params={'value': 'argument'},
    )
    assert run.runtime_config.parameters == {'value': 'argument'}
    assert run.pipeline_version_reference.pipeline_id == pipeline.pipeline_id
    assert (
        run.pipeline_version_reference.pipeline_version_id
        == version.pipeline_version_id
    )
    retrieved = client.get_run(run.run_id)
    assert retrieved.display_name == 'Run from version'
    assert (
        retrieved.pipeline_version_reference.to_dict()
        == run.pipeline_version_reference.to_dict()
    )
    assert (
        client.delete_pipeline_version(
            pipeline.pipeline_id, version.pipeline_version_id
        )
        == {}
    )
    assert client.list_pipeline_versions(pipeline.pipeline_id).total_size == 1
    # C37: as in stock, a pipeline with versions is not deleted silently.
    with pytest.raises(kfp.server_api.ApiException) as refused:
        client.delete_pipeline(pipeline.pipeline_id)
    assert refused.value.status == 400
    assert 'version' in refused.value.reason
    for remaining in client.list_pipeline_versions(
        pipeline.pipeline_id
    ).pipeline_versions:
        client.delete_pipeline_version(
            pipeline.pipeline_id, remaining.pipeline_version_id
        )
    assert client.delete_pipeline(pipeline.pipeline_id) == {}
    assert client.list_pipelines(namespace='team').total_size == 0


def test_host_only_client_uses_managed_namespace(native_api):
    client = kfp.Client(
        host='https://native.invalid/pipeline',
        existing_token='test-token',
        healthz_max_attempts=1,
    )
    assert client.create_experiment('Managed namespace').namespace == 'team'


def test_notebook_links_preserve_operation_namespace(native_api, capsys):
    client, _, _ = native_api
    experiment = client.create_experiment('Linked')
    assert (
        f'?namespace=team#/experiments/details/{experiment.experiment_id}'
        in capsys.readouterr().out
    )


def test_archive_restore_preserves_run_and_works_after_engine_gc(
    native_api, native_store
):
    client, _, _ = native_api
    run = client.create_run_from_pipeline_func(
        stock_program, namespace='team'
    ).run_info
    original = native_store['workflows'][run.run_id]
    assert client.archive_run(run.run_id) == {}
    assert run.run_id in native_store['workflows']
    assert client.get_run(run.run_id).storage_state == 'ARCHIVED'
    listed = client.list_runs(
        filter=json.dumps(
            {
                'predicates': [
                    {
                        'key': 'storage_state',
                        'operation': 'EQUALS',
                        'stringValue': 'ARCHIVED',
                    }
                ]
            }
        )
    )
    assert [item.run_id for item in listed.runs] == [run.run_id]
    original['status'] = {'phase': 'Succeeded'}
    native_store['archives'][run.run_id] = native_store['workflows'].pop(
        run.run_id
    )
    assert client.unarchive_run(run.run_id) == {}
    restored = client.get_run(run.run_id)
    assert restored.run_id == run.run_id
    assert restored.state == 'SUCCEEDED'
    assert restored.storage_state == 'AVAILABLE'
    assert native_store['workflows'] == {}, (
        'Restore must not rerun the workflow'
    )
    assert client.delete_run(run.run_id) == {}
    assert native_store['archives'] == {}
    assert not any(
        item['metadata']
        .get('labels', {})
        .get('pipelines.kubeflow.org/resource')
        == 'run-state'
        for item in native_store['maps'].values()
    )


def test_terminate_delete_and_experiment_deletion_are_non_cascading(
    native_api, native_store
):
    client, _, _ = native_api
    experiment = client.create_experiment('Keep run')
    run = client.create_run_from_pipeline_func(
        stock_program, experiment_id=experiment.experiment_id, namespace='team'
    ).run_info
    assert client.terminate_run(run.run_id) == {}
    assert client.get_run(run.run_id).state == 'CANCELING'
    client.delete_experiment(experiment.experiment_id)
    assert run.run_id in native_store['workflows']
    assert client.delete_run(run.run_id) == {}
    assert native_store['workflows'] == {}


@pytest.mark.parametrize(
    'trigger',
    [
        {'interval_second': 10},
        {'interval_second': '10'},
        {'cron_expression': '0 * * * *'},
    ],
)
def test_recurring_run_defaults_and_lifecycle(
    native_api, native_store, trigger
):
    client, _, _ = native_api
    pipeline = client.upload_pipeline_from_pipeline_func(
        stock_program, namespace='team'
    )
    experiment = client.create_experiment('Scheduled experiment')
    schedule = client.create_recurring_run(
        experiment.experiment_id,
        'Scheduled run',
        pipeline_id=pipeline.pipeline_id,
        params={'value': 'scheduled'},
        **trigger,
    )
    assert isinstance(schedule, server_api.V2RecurringRun)
    assert schedule.status == 'ENABLED'
    assert schedule.no_catchup is False
    assert schedule.max_concurrency == '1'
    if 'interval_second' in trigger:
        assert schedule.trigger.periodic_schedule.interval_second == str(
            trigger['interval_second']
        )
    assert schedule.experiment_id == experiment.experiment_id
    assert schedule.runtime_config.parameters == {'value': 'scheduled'}
    raw = next(iter(native_store['schedules'].values()))
    assert raw['spec']['suspend'] is False
    assert raw['spec']['concurrencyPolicy'] == 'Forbid'
    assert raw['spec']['startingDeadlineSeconds'] > 0
    assert raw['spec']['schedules'] == [
        f'@every {trigger["interval_second"]}s'
        if 'interval_second' in trigger
        else trigger['cron_expression']
    ]
    assert (
        client.list_recurring_runs(experiment_id=experiment.experiment_id)
        .recurring_runs[0]
        .recurring_run_id
        == schedule.recurring_run_id
    )
    assert client.disable_recurring_run(schedule.recurring_run_id) == {}
    assert (
        client.get_recurring_run(schedule.recurring_run_id).status == 'DISABLED'
    )
    assert client.enable_recurring_run(schedule.recurring_run_id) == {}
    assert (
        client.get_recurring_run(schedule.recurring_run_id).status == 'ENABLED'
    )
    assert client.delete_recurring_run(schedule.recurring_run_id) == {}
    assert native_store['schedules'] == {}


def test_recurring_dates_no_catchup_and_cache_override(
    native_api, native_store
):
    client, _, _ = native_api
    pipeline = client.upload_pipeline_from_pipeline_func(
        stock_program, namespace='team'
    )
    schedule = client.create_recurring_run(
        job_name='Disabled interval',
        pipeline_id=pipeline.pipeline_id,
        interval_second=60,
        start_time='2027-01-01T00:00:00Z',
        end_time='2027-02-01T00:00:00Z',
        enabled=False,
        no_catchup=True,
        enable_caching=False,
        namespace='team',
    )
    assert schedule.status == 'DISABLED'
    assert schedule.trigger.periodic_schedule.start_time.year == 2027
    assert schedule.trigger.periodic_schedule.end_time.month == 2
    raw = next(iter(native_store['schedules'].values()))
    assert raw['spec']['startingDeadlineSeconds'] == 0
    assert 'when' in raw['spec']
    assert 'stopStrategy' in raw['spec']
    assert all(
        'memoize' not in template
        for template in raw['spec']['workflowSpec']['templates']
        if 'container' in template
    )


def test_recurring_concurrency_uses_native_workflow_semaphore(
    native_api, native_store
):
    client, _, _ = native_api
    pipeline = client.upload_pipeline_from_pipeline_func(
        stock_program, namespace='team'
    )
    schedule = client.create_recurring_run(
        job_name='Concurrent',
        pipeline_id=pipeline.pipeline_id,
        cron_expression='0 * * * *',
        max_concurrency=3,
        enabled=False,
        namespace='team',
    )
    raw = next(iter(native_store['schedules'].values()))
    reference = raw['spec']['workflowSpec']['synchronization']['semaphores'][0][
        'configMapKeyRef'
    ]
    assert (
        native_store['maps'][reference['name']]['data'][reference['key']] == '3'
    )
    assert schedule.max_concurrency == '3'
    client.delete_recurring_run(schedule.recurring_run_id)
    assert reference['name'] in native_store['maps'], (
        'Already-created workflows must retain their concurrency limit'
    )


@pytest.mark.parametrize(
    'options',
    [
        {'interval_second': -1},
        {'interval_second': True},
        {'interval_second': 1, 'max_concurrency': 0},
        {
            'interval_second': 1,
            'start_time': '2027-02-01T00:00:00Z',
            'end_time': '2027-01-01T00:00:00Z',
        },
    ],
)
def test_recurring_invalid_settings_do_not_create_schedule(
    native_api, native_store, options
):
    client, _, _ = native_api
    pipeline = client.upload_pipeline_from_pipeline_func(
        stock_program, namespace='team'
    )
    with pytest.raises(server_api.ApiException) as error:
        client.create_recurring_run(
            job_name='Invalid',
            pipeline_id=pipeline.pipeline_id,
            namespace='team',
            **options,
        )
    assert error.value.status == 400
    assert native_store['schedules'] == {}


def test_stock_six_field_cron_preserves_public_trigger(
    native_api, native_store
):
    client, _, _ = native_api
    pipeline = client.upload_pipeline_from_pipeline_func(
        stock_program, namespace='team'
    )
    run = client.create_recurring_run(
        job_name='Six-field cron',
        pipeline_id=pipeline.pipeline_id,
        cron_expression='TZ=Europe/Paris 0 15 9 * * ?',
        enabled=False,
        namespace='team',
    )
    assert run.trigger.cron_schedule.cron == 'TZ=Europe/Paris 0 15 9 * * ?'
    raw = next(iter(native_store['schedules'].values()))
    assert raw['spec']['schedules'] == ['15 9 * * *']
    assert raw['spec']['timezone'] == 'Europe/Paris'


def test_public_namespace_context_persistence(native_api):
    client, _, _ = native_api
    assert client.get_user_namespace() == 'team'
    client.set_user_namespace('another-team')
    assert client.get_user_namespace() == 'another-team'
    with open(client._LOCAL_KFP_CONTEXT) as stream:
        assert json.load(stream)['namespace'] == 'another-team'


@pytest.mark.parametrize(
    'root, entry',
    [('s3://cold-storage/a/b', 'archive'), ('gs://exports/a/b', 'gcs-exports')],
)
def test_pipeline_root_override_preserves_version_and_user_literals(
    native_api, native_store, root, entry
):
    client, _, _ = native_api
    pipeline = client.upload_pipeline_from_pipeline_func(
        stock_program, namespace='team'
    )
    version = client.list_pipeline_versions(
        pipeline.pipeline_id
    ).pipeline_versions[0]
    before = json.dumps(
        next(iter(native_store['versions'].values())), sort_keys=True
    )
    run = client.run_pipeline(
        None,
        'Root override',
        pipeline_id=pipeline.pipeline_id,
        version_id=version.pipeline_version_id,
        params={'value': 's3://argo-artifacts/user-data'},
        pipeline_root=root,
    )
    workflow = native_store['workflows'][run.run_id]
    assert client.get_run(run.run_id).runtime_config.pipeline_root == root
    assert (
        workflow['metadata']['annotations'][
            'pipelines.kubeflow.org/artifact-repository'
        ]
        == root
    )
    assert (
        workflow['spec']['arguments']['parameters'][0]['value']
        == 's3://argo-artifacts/user-data'
    )
    # Artifacts carry keys only; the bucket comes from the repository entry
    # that serves the root, selected on the run.
    artifacts = [
        artifact
        for template in workflow['spec']['templates']
        for artifact in template.get('outputs', {}).get('artifacts', [])
    ]
    assert artifacts and all(
        set(artifact['s3']) == {'key'} for artifact in artifacts
    )
    assert workflow['spec']['artifactRepositoryRef'] == {'key': entry}
    assert (
        json.dumps(
            next(iter(native_store['versions'].values())), sort_keys=True
        )
        == before
    )


def test_runs_follow_the_namespace_artifact_repository(
    native_api, native_store
):
    """No root anywhere: the run binds to Argo's default entry for the
    namespace. A root nothing serves is refused before anything is created."""
    client, _, _ = native_api
    pipeline = client.upload_pipeline_from_pipeline_func(
        stock_program, namespace='team'
    )
    version = next(iter(native_store['versions'].values()))
    annotations = version['metadata']['annotations']
    assert annotations['pipelines.kubeflow.org/artifact-repository'] == ''
    assert annotations['pipelines.kubeflow.org/artifact-root-binding'] == 'v1'
    run = client.run_pipeline(
        None, 'Default root', pipeline_id=pipeline.pipeline_id
    )
    workflow = native_store['workflows'][run.run_id]
    assert (
        client.get_run(run.run_id).runtime_config.pipeline_root
        == 's3://argo-artifacts'
    )
    assert (
        workflow['metadata']['annotations'][
            'pipelines.kubeflow.org/artifact-bucket'
        ]
        == 'argo-artifacts'
    )
    assert 'artifactRepositoryRef' not in workflow['spec']
    with pytest.raises(kfp.server_api.exceptions.ApiException) as refused:
        client.run_pipeline(
            None,
            'Nowhere',
            pipeline_id=pipeline.pipeline_id,
            pipeline_root='s3://elsewhere/x',
        )
    assert refused.value.status == 400
    assert (
        's3://elsewhere' in refused.value.reason
        and 's3://cold-storage' in refused.value.reason
    )
    assert len(native_store['workflows']) == 1
    # Without any repository the namespace cannot run pipelines.
    del native_store['maps']['artifact-repositories']
    with pytest.raises(kfp.server_api.exceptions.ApiException) as missing:
        client.run_pipeline(
            None, 'No repository', pipeline_id=pipeline.pipeline_id
        )
    assert missing.value.status == 400
    assert 'artifact repository' in missing.value.reason


def test_decorator_pipeline_root_is_honored(native_api, native_store):
    client, _, _ = native_api

    @dsl.pipeline(
        name='declared-root', pipeline_root='s3://cold-storage/declared'
    )
    def rooted():
        echo(value='hello')

    pipeline = client.upload_pipeline_from_pipeline_func(
        rooted, namespace='team'
    )
    run = client.run_pipeline(
        None, 'Declared root', pipeline_id=pipeline.pipeline_id
    )
    assert (
        client.get_run(run.run_id).runtime_config.pipeline_root
        == 's3://cold-storage/declared'
    )
    assert native_store['workflows'][run.run_id]['spec'][
        'artifactRepositoryRef'
    ] == {'key': 'archive'}


def test_stock_cli_experiment_lifecycle_uses_native_http(native_api):
    from click.testing import CliRunner
    from kfp.cli.cli import cli

    client, _, _ = native_api
    runner = CliRunner()
    options = [
        '--endpoint',
        'https://native.invalid/pipeline',
        '--namespace',
        'team',
        '--existing-token',
        'test-token',
        '--output',
        'json',
    ]

    def invoke(*args):
        result = runner.invoke(cli, [*options, *args], obj={})
        assert result.exit_code == 0, (result.output, result.exception)
        return result.output

    invoke('experiments', 'create', 'CLI experiment')
    experiment = client.get_experiment(experiment_name='CLI experiment')
    rows = json.loads(invoke('experiment', 'list'))
    assert rows[0]['experiment_id'] == experiment.experiment_id
    invoke('experiment', 'archive', '--experiment-id', experiment.experiment_id)
    assert (
        client.get_experiment(experiment.experiment_id).storage_state
        == 'ARCHIVED'
    )
    invoke(
        'experiment', 'unarchive', '--experiment-id', experiment.experiment_id
    )
    assert (
        client.get_experiment(experiment.experiment_id).storage_state
        == 'AVAILABLE'
    )


def test_experiment_run_and_schedule_timestamps_are_derived(
    native_api, native_store
):
    """last_run_created_at, run state_history/scheduled_at and recurring-run
    updated_at come from native resources instead of staying None (U49, U50,
    U52)."""
    client, _, _ = native_api
    experiment = client.create_experiment('Timestamps')
    assert experiment.last_run_created_at is None
    submitted = client.create_run_from_pipeline_func(
        stock_program,
        arguments={'value': 'hello'},
        experiment_id=experiment.experiment_id,
    )
    fetched = client.get_experiment(experiment_id=experiment.experiment_id)
    assert (
        fetched.last_run_created_at.isoformat() == '2026-01-01T00:00:00+00:00'
    )
    assert (
        client.list_experiments().experiments[0].last_run_created_at
        == fetched.last_run_created_at
    )
    run = client.get_run(submitted.run_id)
    assert [s.state for s in run.state_history] == ['PENDING']
    assert run.scheduled_at == run.created_at
    native_store['workflows'][submitted.run_id]['status'].update(
        phase='Succeeded',
        startedAt='2026-01-01T00:00:03Z',
        finishedAt='2026-01-01T00:00:09Z',
    )
    run = client.get_run(submitted.run_id)
    assert [(s.state, s.update_time.second) for s in run.state_history] == [
        ('PENDING', 0),
        ('RUNNING', 3),
        ('SUCCEEDED', 9),
    ]
    pipeline = client.upload_pipeline_from_pipeline_func(
        stock_program, namespace='team'
    )
    schedule = client.create_recurring_run(
        experiment.experiment_id,
        'Scheduled run',
        pipeline_id=pipeline.pipeline_id,
        cron_expression='0 * * * *',
    )
    assert schedule.updated_at == schedule.created_at
    raw = next(iter(native_store['schedules'].values()))
    raw['metadata']['managedFields'] = [
        {'manager': 'kfp', 'time': '2026-01-01T00:00:00Z'},
        {'manager': 'kubectl-edit', 'time': '2026-01-02T12:00:00Z'},
    ]
    assert (
        client.get_recurring_run(
            schedule.recurring_run_id
        ).updated_at.isoformat()
        == '2026-01-02T12:00:00+00:00'
    )


def test_upload_pipeline_version_from_a_package_path(
    native_api, native_store, tmp_path, capsys
):
    from kfp import compiler

    client, _, _ = native_api
    package = str(tmp_path / 'pipeline.yaml')
    compiler.Compiler().compile(stock_program, package)
    pipeline = client.upload_pipeline(
        package, pipeline_name='Packaged', namespace='team'
    )
    capsys.readouterr()
    version = client.upload_pipeline_version(
        package,
        'Second cut',
        pipeline_id=pipeline.pipeline_id,
        description='Regenerated package',
    )
    assert isinstance(version, server_api.V2PipelineVersion)
    assert version.pipeline_id == pipeline.pipeline_id
    assert version.display_name == 'Second cut'
    assert version.description == 'Regenerated package'
    assert version.pipeline_spec['kind'] == 'WorkflowTemplate'
    assert (
        client.get_pipeline_version(
            pipeline.pipeline_id, version.pipeline_version_id
        ).description
        == 'Regenerated package'
    )
    assert client.list_pipeline_versions(pipeline.pipeline_id).total_size == 2
    stored = next(
        item
        for item in native_store['versions'].values()
        if item['metadata']['uid'] == version.pipeline_version_id
    )
    assert (
        stored['metadata']['labels']['pipelines.kubeflow.org/pipeline']
        == pipeline.pipeline_id
    )
    assert (
        stored['metadata']['annotations'][
            'pipelines.kubeflow.org/version-display-name'
        ]
        == 'Second cut'
    )
    assert (
        f'?namespace=team#/pipelines/details/{pipeline.pipeline_id}'
        f'/version/{version.pipeline_version_id}' in capsys.readouterr().out
    )
    with pytest.raises(server_api.ApiException) as duplicate:
        client.upload_pipeline_version(
            package, 'Second cut', pipeline_id=pipeline.pipeline_id
        )
    assert duplicate.value.status == 409
    assert client.list_pipeline_versions(pipeline.pipeline_id).total_size == 2


def test_upload_pipeline_version_resolves_shared_pipeline_names(
    native_api, tmp_path
):
    from kfp import compiler

    client, _, _ = native_api
    package = str(tmp_path / 'pipeline.yaml')
    compiler.Compiler().compile(stock_program, package)
    shared = client.upload_pipeline(package, pipeline_name='Shared program')
    assert shared.namespace is None
    version = client.upload_pipeline_version(
        package, 'By name', pipeline_name='Shared program'
    )
    assert version.pipeline_id == shared.pipeline_id
    assert (
        client.get_pipeline_version(
            shared.pipeline_id, version.pipeline_version_id
        ).display_name
        == 'By name'
    )
    for selector in [
        {},
        {'pipeline_id': shared.pipeline_id, 'pipeline_name': 'Shared program'},
    ]:
        with pytest.raises(
            ValueError, match='Either pipeline_id or pipeline_name is required'
        ):
            client.upload_pipeline_version(package, 'Rejected', **selector)
    with pytest.raises(server_api.ApiException) as missing:
        client.upload_pipeline_version(
            package, 'Orphan', pipeline_name='No such pipeline'
        )
    assert missing.value.status == 404
    assert client.list_pipeline_versions(shared.pipeline_id).total_size == 2


def test_get_pipeline_returns_private_and_shared_records(native_api):
    client, _, requests_seen = native_api
    private = client.upload_pipeline_from_pipeline_func(
        stock_program, pipeline_name='Private', namespace='team'
    )
    shared = client.upload_pipeline_from_pipeline_func(
        stock_program, pipeline_name='Shared'
    )
    requests_seen.clear()
    fetched = client.get_pipeline(private.pipeline_id)
    assert isinstance(fetched, server_api.V2Pipeline)
    assert fetched.to_dict() == private.to_dict()
    assert fetched.namespace == 'team'
    assert client.get_pipeline(shared.pipeline_id).to_dict() == shared.to_dict()
    assert client.get_pipeline(shared.pipeline_id).namespace is None
    with pytest.raises(server_api.ApiException) as error:
        client.get_pipeline('missing')
    assert error.value.status == 404
    assert all('/apis/v2' not in path for _, path, _ in requests_seen)


def test_get_kfp_healthz_probes_argo_info(native_api):
    client, _, requests_seen = native_api
    requests_seen.clear()
    response = client.get_kfp_healthz()
    assert isinstance(response, server_api.V2GetHealthzResponse)
    assert [(method, path) for method, path, _ in requests_seen] == [
        ('GET', '/argo/api/v1/info')
    ]


def test_get_kfp_healthz_reports_the_deployment_scope(native_api, monkeypatch):
    """C40 (docs/compatibility.md): a namespaced Argo Server, which the
    fixture's ``managedNamespace`` models, is a single-namespace deployment; a
    cluster-wide server is the multi-user one."""
    client, _, _ = native_api
    response = client.get_kfp_healthz()
    assert response.multi_user is False
    assert response.pipeline_store == 'kubernetes'
    original = requests.Session.request

    def request(session, method, url, **kwargs):
        response = original(session, method, url, **kwargs)
        if urlsplit(url).path.endswith('/argo/api/v1/info'):
            response._content = json.dumps({'modals': {}}).encode()
        return response

    monkeypatch.setattr(requests.Session, 'request', request)
    assert client.get_kfp_healthz().multi_user is True


def test_get_kfp_healthz_retries_then_reports_the_failure(
    native_api, monkeypatch
):
    client, _, requests_seen = native_api
    original = requests.Session.request
    status = {'code': 503}

    def request(session, method, url, **kwargs):
        if urlsplit(url).path.endswith('/argo/api/v1/info'):
            response = requests.Response()
            response.status_code = status['code']
            response.reason = 'Unavailable'
            response._content = b'{}'
            requests_seen.append((method, urlsplit(url).path, kwargs))
            return response
        return original(session, method, url, **kwargs)

    monkeypatch.setattr(requests.Session, 'request', request)
    requests_seen.clear()
    with pytest.raises(TimeoutError, match='after 2 attempts'):
        client.get_kfp_healthz(sleep_duration=0, max_attempts=2)
    assert len(requests_seen) == 2
    status['code'] = 404
    with pytest.raises(RuntimeError, match='does not expose'):
        client.get_kfp_healthz(sleep_duration=0, max_attempts=3)
    with pytest.raises(ValueError, match='max_attempts must be an integer'):
        client.get_kfp_healthz(max_attempts=0)


def test_deprecated_job_aliases_delegate_to_recurring_runs(
    native_api, native_store
):
    client, _, _ = native_api
    pipeline = client.upload_pipeline_from_pipeline_func(
        stock_program, namespace='team'
    )
    schedule = client.create_recurring_run(
        job_name='Aliased',
        pipeline_id=pipeline.pipeline_id,
        cron_expression='0 * * * *',
        namespace='team',
    )
    recurring_run_id = schedule.recurring_run_id
    for alias, target, status in [
        ('disable_job', 'disable_recurring_run', 'DISABLED'),
        ('enable_job', 'enable_recurring_run', 'ENABLED'),
        ('delete_job', 'delete_recurring_run', None),
    ]:
        with pytest.warns(DeprecationWarning) as warned:
            assert getattr(client, alias)(recurring_run_id) == {}
        assert len(warned) == 1
        assert str(warned[0].message) == (
            f'`{alias}` is deprecated. Please use `{target}` instead.'
            f'\nReroute to calling `{target}(recurring_run_id="{recurring_run_id}")`'
        )
        assert warned[0].filename == __file__, (
            'The warning must point at the caller, as stock does'
        )
        if status:
            assert client.get_recurring_run(recurring_run_id).status == status
    assert native_store['schedules'] == {}


def test_default_experiment_cannot_be_deleted(native_api):
    """C38: stock refused to delete the default experiment."""
    client, _, _ = native_api

    @dsl.component
    def step():
        pass

    @dsl.pipeline
    def pipeline():
        step()

    run = client.create_run_from_pipeline_func(pipeline, arguments={})
    default = client.get_experiment(experiment_name='Default', namespace='team')
    assert client.get_run(run.run_id).experiment_id == default.experiment_id
    with pytest.raises(kfp.server_api.ApiException) as refused:
        client.delete_experiment(default.experiment_id)
    assert refused.value.status == 400
    assert (
        client.get_experiment(experiment_id=default.experiment_id).display_name
        == 'Default'
    )


def test_experiment_names_are_unique_per_namespace(native_api):
    """C55: stock refused a second experiment with the same name (409); the
    ConfigMap name derives from the display name so Kubernetes enforces it."""
    client, _, _ = native_api
    first = client.create_experiment('Shared name', namespace='team')
    # The stock wrapper looks the name up first and returns the existing one.
    assert (
        client.create_experiment('Shared name', namespace='team').experiment_id
        == first.experiment_id
    )
    # A concurrent creator that lost the race gets stock's 409 from the API.
    with pytest.raises(kfp.server_api.ApiException) as refused:
        client._experiment_api.experiment_service_create_experiment(
            server_api.V2Experiment(
                display_name='Shared name', namespace='team'
            )
        )
    assert refused.value.status == 409
    assert 'already exists' in refused.value.reason
    assert (
        client.get_experiment(
            experiment_name='Shared name', namespace='team'
        ).experiment_id
        == first.experiment_id
    )
