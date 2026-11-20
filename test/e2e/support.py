# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Helpers shared by the live suite: submit, wait, and read Argo state."""

import os
import time
from uuid import uuid4

EXPERIMENT = 'SDK end-to-end'
TERMINAL = ('SUCCEEDED', 'FAILED', 'CANCELED')

# A prebuilt image carrying this SDK avoids a PyPI install in every pod and
# proves content-addressed image identity; otherwise components use stock
# defaults and install KFP from PyPI, as a user's would.
IMAGE = os.environ.get('KFP_TEST_IMAGE')
COMPONENT = {'base_image': IMAGE, 'install_kfp_package': False} if IMAGE else {}


def submit(client, function, arguments=None, name=None, **options):
    """Create a run in the suite's experiment with a unique, searchable
    name."""
    return client.create_run_from_pipeline_func(
        function,
        arguments=arguments or {},
        run_name=(name or function.name) + ' ' + uuid4().hex[:8],
        experiment_name=EXPERIMENT,
        namespace=client.get_user_namespace(),
        **options,
    )


def run_pipeline(client, function, arguments=None, timeout=600, **options):
    """Submit and wait; returns (submitted, completed)."""
    submitted = submit(client, function, arguments, **options)
    return submitted, submitted.wait_for_run_completion(timeout=timeout)


def workflow(client, completed):
    """The hydrated Argo workflow behind a completed run."""
    metadata = completed.pipeline_spec['metadata']
    return client._run_api.transport.request(
        'GET',
        f'/argo/api/v1/workflows/{metadata["namespace"]}/{metadata["name"]}',
    )


def nodes(raw):
    return list((raw.get('status') or {}).get('nodes', {}).values())


def node(raw, display_name):
    return next(n for n in nodes(raw) if n.get('displayName') == display_name)


def node_output(entry, name='Output'):
    return next(
        p['value']
        for p in entry.get('outputs', {}).get('parameters', [])
        if p['name'] == name
    )


def task(completed, display_name):
    return next(t for t in completed.tasks if t.display_name == display_name)


def task_output(entry, name='Output'):
    return next(
        p.value for p in entry.outputs.parameters if p.parameter_key == name
    )


def failures(completed):
    return [
        (t.display_name, t.state, t.lifecycle_message)
        for t in (completed.tasks or [])
        if t.state in ('FAILED', 'RUNTIME_STATE_UNSPECIFIED')
    ]


def phases(raw):
    return [
        (n.get('displayName'), n.get('phase'), n.get('message'))
        for n in nodes(raw)
    ]


def pods(client, raw):
    """Pods of a workflow while they exist, through the Kubernetes API."""
    metadata = raw['metadata']
    return client._run_api.transport.collection(
        f'/kubernetes/api/v1/namespaces/{metadata["namespace"]}/pods',
        params={
            'labelSelector': 'workflows.argoproj.io/workflow='
            + metadata['name']
        },
        kubernetes=True,
    )


def main_container(pod):
    return next(c for c in pod['spec']['containers'] if c['name'] == 'main')


def wait_without_errors(client, submitted, timeout, error_nodes=()):
    """Wait for a terminal state, but stop early (and terminate the run) when
    one of `error_nodes` reports an Argo Error, which would otherwise hang
    until the timeout."""
    deadline = time.monotonic() + timeout
    while True:
        completed = client.get_run(submitted.run_id)
        raw = workflow(client, completed)
        if completed.state in TERMINAL:
            return completed, raw
        errored = [
            n
            for n in nodes(raw)
            if n.get('phase') == 'Error'
            and (not error_nodes or n.get('displayName') in error_nodes)
        ]
        if errored:
            client.terminate_run(submitted.run_id)
            raise AssertionError(phases(raw))
        if time.monotonic() > deadline:
            client.terminate_run(submitted.run_id)
            raise AssertionError(f'Run timeout after {timeout}s: {phases(raw)}')
        time.sleep(3)
