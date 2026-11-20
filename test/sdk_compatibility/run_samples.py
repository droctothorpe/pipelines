# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Execute compiled stock sample DSL on an explicitly configured native cluster.

Set KFP_TEST_HOST, KFP_TEST_NAMESPACE and KFP_TEST_TOKEN. Compiled manifests and
per-case results are retained. No cluster resources are deleted by this runner.
Use --include to select source paths or pipeline names. It never changes samples.
--parallelism bounds a submission copy; --disable-caching explicitly exercises
current runtime code without clearing caches or changing the SDK default.
Compilation failures, including known stock failures, retain a nonzero exit status.
"""

import argparse
import json
import os
import time
from pathlib import Path
from uuid import uuid4

import kfp
import yaml
from sample_corpus import compile_samples

# Prerequisites are recorded, not counted as successful execution.
PREREQUISITES = {
    'artifact_previews': 'Requires the preview-capable SDK runtime and large optional model/dataframe dependencies.',
    'kubernetes_pvc': 'Requires a PVC-capable workflow service account and StorageClass standard.',
    'runtime_resource_request_gpu': 'Requires a matching GPU device/plugin and compatible image architecture.',
    'parallel_join': 'Requires GCS access and compatible cloud-sdk image architecture.',
    'secret': 'Requires Google Cloud credentials/project and a compatible legacy runtime image.',
    'sequential': 'Requires GCS access and compatible cloud-sdk image architecture.',
    'kfp_env_validation': 'Requires Google Cloud credentials and repaired pre-existing notebook definitions.',
}


def run(args):
    token = os.environ.get('KFP_TEST_TOKEN', '')
    if not token:
        raise ValueError(
            'KFP_TEST_TOKEN must be non-empty before creating a client.'
        )
    parallelism = getattr(args, 'parallelism', None)
    if parallelism is not None and parallelism <= 0:
        raise ValueError('Verification parallelism must be positive.')
    disable_caching = getattr(args, 'disable_caching', False)
    rows = compile_samples(args.output)
    client = kfp.Client(
        host=os.environ['KFP_TEST_HOST'],
        namespace=os.environ['KFP_TEST_NAMESPACE'],
        existing_token=token,
    )
    report_path = args.output / 'execution.json'
    for row in rows:
        if row['compile'] != 'passed':
            continue
        identity = row['source'] + ':' + row['pipeline']
        if args.include and not any(part in identity for part in args.include):
            row.update(execution='not_selected')
            continue
        requirement = next(
            (
                reason
                for key, reason in PREREQUISITES.items()
                if key in row['source']
            ),
            None,
        )
        if requirement and not args.include:
            row.update(execution='prerequisite_required', reason=requirement)
            continue
        parameters = {}
        if '/caching/' in row['source']:
            parameters = {'seconds': 1}
        if '/resource_spec/' in row['source'] and 'gpu' not in row['source']:
            parameters = {'n': 10000}
        if '/condition/condition_v2.py' in row['source']:
            parameters = {'force_flip_result': 'heads'}
        row['parameters'] = parameters
        row['caching'] = 'disabled_explicitly' if disable_caching else 'default'
        started = time.monotonic()
        try:
            package = row['manifest']
            if parallelism is not None:
                original = Path(package)
                manifest = yaml.safe_load(original.read_text())
                current = manifest['spec'].get('parallelism') or parallelism
                row['parallelism'] = min(parallelism, current)
                manifest['spec']['parallelism'] = row['parallelism']
                derived = args.output / (original.stem + '.execution.json')
                derived.write_text(json.dumps(manifest, indent=2))
                package = row['submitted_manifest'] = str(derived)
            submitted = client.create_run_from_pipeline_package(
                package,
                arguments=parameters,
                run_name='Stock sample '
                + row['pipeline']
                + ' '
                + uuid4().hex[:8],
                experiment_name='Stock sample compatibility',
                namespace=os.environ['KFP_TEST_NAMESPACE'],
                service_account=args.service_account,
                enable_caching=False if disable_caching else None,
            )
            row['run_id'] = submitted.run_id
            completed = submitted.wait_for_run_completion(timeout=args.timeout)
            expected = (
                'FAILED'
                if '/exit_handler/' in row['source']
                or 'DSL - Control structures' in row['source']
                else 'SUCCEEDED'
            )
            row.update(
                state=completed.state,
                expected_state=expected,
                execution='passed' if completed.state == expected else 'failed',
            )
            name = completed.pipeline_spec['metadata']['name']
            workflow = client._run_api.transport.request(
                'GET',
                f'/argo/api/v1/workflows/{os.environ["KFP_TEST_NAMESPACE"]}/{name}',
            )
            nodes = workflow.get('status', {}).get('nodes', {})
            row['nodes'] = [
                {
                    'name': node.get('displayName'),
                    'type': node.get('type'),
                    'phase': node.get('phase'),
                    'message': node.get('message'),
                    'cache_hit': node.get('memoizationStatus', {}).get('hit'),
                    'outputs': node.get('outputs', {}).get('parameters', []),
                    'artifacts': node.get('outputs', {}).get('artifacts', []),
                }
                for node in nodes.values()
            ]
            if (
                '/artifact_previews/' in row['source']
                and completed.state == 'SUCCEEDED'
            ):
                count = 0
                disabled = 'disabled' in row['pipeline']
                for node in nodes.values():
                    if (
                        node.get('type') != 'Pod'
                        or node.get('phase') != 'Succeeded'
                    ):
                        continue
                    metadata = client._run_api.transport.request(
                        'GET',
                        f'/argo/artifacts/{os.environ["KFP_TEST_NAMESPACE"]}/{name}/{node["id"]}/kfp-metadata',
                    )
                    for artifact in metadata.get('artifacts', []):
                        descriptor = artifact['metadata'].get('_kfp_preview')
                        assert bool(descriptor) is not disabled, artifact
                        if descriptor:
                            preview = client._run_api.transport.request(
                                'GET',
                                f'/argo/artifacts/{os.environ["KFP_TEST_NAMESPACE"]}/{name}/{node["id"]}/{artifact["port"]}-preview',
                            )
                            assert preview, artifact
                            count += 1
                row['verified_previews'] = count
                for node in nodes.values():
                    for parameter in node.get('outputs', {}).get(
                        'parameters', []
                    ):
                        if parameter['name'] in (
                            'kfp-uri-datasets',
                            'kfp-uri-models',
                            'kfp-uri-dataframes',
                            'kfp-uri-pytorch_models',
                        ):
                            values = json.loads(parameter['value'])
                            assert values and all(
                                isinstance(value, str)
                                and value.startswith('s3://')
                                and '{{' not in value
                                for value in values
                            ), values
                if not disabled:
                    assert count > 0, 'No artifact previews were generated'
            if expected == 'FAILED':
                cleanup = [
                    node
                    for node in nodes.values()
                    if node.get('type') == 'Pod'
                    and node.get('displayName') == 'exit'
                ]
                if not cleanup or any(
                    node.get('phase') != 'Succeeded' for node in cleanup
                ):
                    row.update(
                        execution='failed',
                        reason='Expected failing body with a successful exit handler.',
                    )
        except Exception as error:
            row.update(
                execution='failed', error=f'{type(error).__name__}: {error}'
            )
        row['seconds'] = round(time.monotonic() - started, 2)
        report_path.write_text(json.dumps(rows, indent=2))
        print(
            row['execution'].upper(),
            identity,
            row.get('state', row.get('error')),
            flush=True,
        )
    report_path.write_text(json.dumps(rows, indent=2))
    return rows


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--include', action='append')
    parser.add_argument('--timeout', type=int, default=300)
    parser.add_argument('--service-account')
    parser.add_argument(
        '--parallelism',
        type=int,
        help='Bound test concurrency without increasing a pipeline limit.',
    )
    parser.add_argument(
        '--disable-caching',
        action='store_true',
        help='Explicit cold-execution verification; never clears existing caches.',
    )
    rows = run(parser.parse_args())
    raise SystemExit(
        any(
            row.get('execution') == 'failed' or row.get('compile') == 'failed'
            for row in rows
        )
    )
