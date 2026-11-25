# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""``dsl.get_uri()`` inside a native pod answers as it does on stock's launcher
(U50)."""

import pytest
from kfp import dsl

from e2e import support
from e2e.support import COMPONENT


@dsl.component(**COMPONENT)
def task_root() -> str:
    import warnings

    from kfp import dsl

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        uri = dsl.get_uri(suffix='model')
    messages = [str(warning.message) for warning in caught]
    assert any('not yet supported' in message for message in messages), messages
    return uri


@dsl.component(**COMPONENT)
def own_artifact() -> dsl.Artifact:
    from kfp import dsl

    # The documented pythonic return shape; on the KFP backend the URI is ''.
    return dsl.Artifact(uri=dsl.get_uri(suffix='model'), metadata={'data': 1})


@dsl.pipeline(name='native-task-root')
def task_root_pipeline() -> str:
    own_artifact().set_caching_options(False)
    return task_root().set_caching_options(False).output


@pytest.mark.full
def test_get_uri_matches_the_stock_backend(client, record):
    """The helper warns and returns '' (stock's launcher supplies no task
    root), and a returned artifact without a URI fails the same way stock
    does: the payload was never written to the assigned location."""
    submitted, done = support.run_pipeline(client, task_root_pipeline)
    raw = support.workflow(client, done)
    assert done.state == 'FAILED', support.phases(raw)
    assert support.node(raw, 'task-root')['phase'] == 'Succeeded'
    assert support.node_output(support.node(raw, 'task-root')) == ''
    # Argo's node message carries only the exit code; the runtime unit test
    # pins the "was not written" error the pod log shows.
    assert support.node(raw, 'own-artifact')['phase'] == 'Failed'
    record(run_id=submitted.run_id, state=done.state)
