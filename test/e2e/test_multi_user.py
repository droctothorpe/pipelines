# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Multi-user mode: the gateway names the user, the proxy authorizes each
request for that user in the namespace it reaches, and tenant namespaces run
pipelines under the cluster-wide controller.

Needs a deployment generated with ``--auth-mode multi-user``, a tenant namespace
prepared with ``--tenant``, an editor bound to ``kfp-native-edit`` and a viewer
bound to ``kfp-native-view`` there. The suite reaches the proxy directly and sets
the identity header itself, as stock's multi-user tests do; behind a real gateway
the header comes from the login.
"""

import os
import time

import pytest
import requests
from kfp import dsl
from kfp.server_api import ApiException

from e2e import support

TENANT = os.environ.get('KFP_TEST_TENANT', 'kfp-tenant-a')
EDITOR = os.environ.get('KFP_TEST_EDITOR_USER', 'alice@example.com')
VIEWER = os.environ.get('KFP_TEST_VIEWER_USER', 'bob@example.com')
HEADER = os.environ.get('KFP_TEST_USERID_HEADER', 'kubeflow-userid')

pytestmark = pytest.mark.smoke


@dsl.component(**support.COMPONENT)
def produce(text: str, data: dsl.Output[dsl.Dataset]):
    with open(data.path, 'w') as handle:
        handle.write(text)


@dsl.component(**support.COMPONENT)
def consume(data: dsl.Input[dsl.Dataset]) -> str:
    with open(data.path) as handle:
        return handle.read()


@dsl.pipeline
def tenant_pipeline(text: str = 'tenant'):
    consume(data=produce(text=text).outputs['data'])


@pytest.fixture(scope='module')
def multi_user(settings):
    response = requests.get(settings.host + '/config.json', timeout=10)
    if (
        response.status_code != 200
        or response.json().get('authMode') != 'multi-user'
    ):
        pytest.skip('needs a multi-user deployment')
    return settings


def as_user(settings, user, namespace):
    import kfp

    # The proxy ignores the bearer token in this mode; the client requires one.
    return support.as_user(
        kfp.Client(
            host=settings.host, namespace=namespace, existing_token='gateway'
        ),
        user,
    )


def raw(settings, path, user=None, method='GET'):
    headers = {HEADER: user} if user else {}
    return requests.request(
        method, settings.host + path, headers=headers, timeout=30
    )


def run_ids(client, namespace):
    return {
        run.run_id
        for run in client.list_runs(
            namespace=namespace, page_size=50, sort_by='created_at desc'
        ).runs
    }


@pytest.fixture(scope='module')
def editor_run(multi_user):
    client = as_user(multi_user, EDITOR, TENANT)
    submitted, completed = support.run_pipeline(
        client, tenant_pipeline, {'text': 'hello tenant'}, enable_caching=False
    )
    return client, submitted, completed


def test_editor_runs_a_pipeline_in_the_tenant_namespace(editor_run, record):
    client, submitted, completed = editor_run
    assert completed.state == 'SUCCEEDED', support.failures(completed)
    workflow = support.workflow(client, completed)
    assert workflow['metadata']['namespace'] == TENANT
    assert (
        support.node_output(support.node(workflow, 'consume')) == 'hello tenant'
    )
    assert submitted.run_id in run_ids(client, TENANT)
    record(run_id=submitted.run_id, namespace=TENANT, user=EDITOR)


def test_viewer_reads_but_cannot_write(multi_user, editor_run, record):
    _, submitted, _ = editor_run
    viewer = as_user(multi_user, VIEWER, TENANT)
    assert submitted.run_id in run_ids(viewer, TENANT)
    assert viewer.get_run(submitted.run_id).state == 'SUCCEEDED'
    with pytest.raises(ApiException) as denied:
        viewer.create_experiment('viewer experiment', namespace=TENANT)
    assert denied.value.status == 403
    with pytest.raises(ApiException) as denied:
        support.submit(viewer, tenant_pipeline)
    assert denied.value.status == 403
    record(user=VIEWER, denied=['create experiment', 'create run'])


def test_users_stay_inside_their_namespaces(multi_user, editor_run, record):
    platform = multi_user.namespace
    editor = as_user(multi_user, EDITOR, platform)
    with pytest.raises(ApiException) as denied:
        editor.list_runs(namespace=platform, page_size=5)
    assert denied.value.status == 403
    # No gateway identity: refused before anything is looked at.
    assert (
        raw(multi_user, f'/argo/api/v1/workflows/{TENANT}').status_code == 401
    )
    # Cluster-wide and unmapped paths are refused for everyone.
    for path in (
        '/kubernetes/apis/argoproj.io/v1alpha1/workflows',
        '/argo/api/v1/archived-workflows',
        '/argo/api/v1/cluster-workflow-templates',
        '/kubernetes/api/v1/namespaces',
    ):
        assert raw(multi_user, path, EDITOR).status_code == 403, path
    # Open metadata needs an identity but no namespace.
    assert raw(multi_user, '/argo/api/v1/info', EDITOR).status_code == 200
    record(platform_denied=True)


def test_archived_runs_keep_their_namespace(multi_user, editor_run, record):
    client, submitted, _ = editor_run
    uid = submitted.run_id
    path = f'/argo/api/v1/archived-workflows/{uid}?namespace={TENANT}'
    deadline = time.monotonic() + 120
    while (archived := raw(multi_user, path, EDITOR)).status_code != 200:
        assert time.monotonic() < deadline, archived.status_code
        time.sleep(3)
    assert archived.json()['metadata']['namespace'] == TENANT
    # Claiming another namespace for the uid does not move it there.
    assert (
        raw(
            multi_user,
            f'/argo/api/v1/archived-workflows/{uid}?namespace={multi_user.namespace}',
            EDITOR,
        ).status_code
        == 403
    )
    # A viewer without rights in the tenant cannot read it under any namespace.
    assert (
        raw(
            multi_user,
            f'/argo/api/v1/archived-workflows/{uid}?namespace={TENANT}',
            'carol@example.com',
        ).status_code
        == 403
    )
    assert client.get_run(uid).run_id == uid
    record(archived_uid=uid)
