# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""SDK-created fixtures for the live browser suite.

``python test/e2e/fixtures.py <kind> <output.json>`` creates the resource through
the public client against ``KFP_TEST_HOST`` and writes what the browser test
needs to find it. Kinds: ``interop``, ``markdown``, ``classification``,
``preview``, ``validation``, ``nested-importer``, ``optional-version``,
``artifact-list-version`` and ``compile:<pipeline>`` (writes a package path).
"""

import json
import os
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from e2e import support  # noqa: E402
from e2e.corpus import ROOT, definitions  # noqa: E402


def _run(client, function, arguments=None, expected='SUCCEEDED', timeout=600):
    submitted, done = support.run_pipeline(
        client, function, arguments, timeout=timeout, enable_caching=False
    )
    assert done.state == expected, support.failures(done) or done.state
    raw = support.workflow(client, done)
    return {
        'run_id': submitted.run_id,
        'namespace': raw['metadata']['namespace'],
        'workflow': raw['metadata']['name'],
        'state': done.state,
    }


def _version(client, namespace, function, label):
    suffix = uuid4().hex[:8]
    experiment = client.create_experiment(f'UI {label} {suffix}')
    uploaded = client.upload_pipeline_from_pipeline_func(
        function, pipeline_name=f'UI {label} {suffix}', namespace=namespace
    )
    version = client.list_pipeline_versions(
        uploaded.pipeline_id
    ).pipeline_versions[0]
    return {
        'namespace': namespace,
        'pipeline_id': uploaded.pipeline_id,
        'version_id': version.pipeline_version_id,
        'experiment_id': experiment.experiment_id,
        'experiment_name': experiment.display_name,
    }


def create(client, namespace, kind):
    if kind == 'interop':
        from e2e.pipelines.ui_interop import create as interop

        return interop(client, namespace)
    if kind == 'markdown':
        from e2e.pipelines.visualizations import markdown_pipeline

        return _run(client, markdown_pipeline)
    if kind == 'classification':
        from e2e.pipelines.visualizations import classification_pipeline

        return _run(client, classification_pipeline)
    if kind == 'preview':
        source = ROOT / 'samples/core/artifact_previews/artifact_previews.py'
        namespace_, _, error = definitions(source, source.read_text())
        assert error is None, error
        return _run(
            client, namespace_['artifact_preview_pipeline'], timeout=900
        )
    if kind == 'validation':
        from e2e.pipelines.container_scalars import pipeline

        return _run(client, pipeline, {'bad': 'integer'}, expected='FAILED')
    if kind == 'nested-importer':
        from e2e.pipelines.nested_importer import pipeline

        return _run(client, pipeline)
    if kind == 'optional-version':
        from e2e.pipelines.optional_inputs import pipeline

        return _version(client, namespace, pipeline, 'optional inputs')
    if kind == 'artifact-list-version':
        from e2e.pipelines.artifact_lists import pipeline

        return _version(client, namespace, pipeline, 'artifact lists')
    if kind.startswith('compile:'):
        from kfp import compiler

        name = kind.split(':', 1)[1]
        module = __import__(f'e2e.pipelines.{name}', fromlist=['pipeline'])
        target = (
            Path(os.environ.get('KFP_TEST_OUTPUT', '/tmp'))
            / f'{name}-{uuid4().hex[:8]}.yaml'
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        compiler.Compiler().compile(module.pipeline, str(target))
        return {'package': str(target), 'name': module.pipeline.name}
    raise SystemExit(f'Unknown fixture kind {kind!r}')


if __name__ == '__main__':
    import kfp

    kind, target = sys.argv[1], Path(sys.argv[2])
    namespace = os.environ.get('KFP_TEST_NAMESPACE', 'kfp-argo')
    client = kfp.Client(
        host=os.environ['KFP_TEST_HOST'],
        namespace=namespace,
        existing_token=os.environ['KFP_TEST_TOKEN'],
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(create(client, namespace, kind)))
    print(kind, 'fixture written to', target)
