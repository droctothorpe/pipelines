# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""The stock sample corpus as test cases: what to run, with which inputs, and
what outcome counts as a pass. The samples themselves are never edited."""

import json
from dataclasses import dataclass, field
from pathlib import Path

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
EXPECTED_FAILED = ('/exit_handler/',)
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

    @property
    def id(self):
        return self.source.removeprefix('samples/') + ':' + self.pipeline


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
                if (
                    key in relative
                    or key
                    == relative.removeprefix('samples/core/') + ':' + name
                ):
                    case.prerequisite = reason
            case.timeout = LONG.get(name, case.timeout)
            result.append(case)
    return result


def frozen_baseline():
    """The captured stock compile results, to tell baseline failures apart."""
    fixture = json.loads((ROOT / 'test/data/stock_samples.json').read_text())
    return {
        row['source'] + ':' + row['pipeline']: row['compile']
        for row in fixture['samples']
    }


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
