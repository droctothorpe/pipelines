# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Read-only check of the stock kube_context connection interface.

Example: KUBECONFIG="$HOME/.kube/config" uv run python \
    test/sdk_compatibility/kube_context.py --context orbstack --namespace kfp-argo

Add --run to compile and execute the unchanged execution-order sample.
Use --service-account-token with KFP_TEST_TOKEN to select token identity instead.
This reproducer never prints credentials or modifies the user's SDK context file.
"""

import argparse
import os
import tempfile
from pathlib import Path

import kfp

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--context', required=True)
    parser.add_argument('--namespace', required=True)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--service-account-token', action='store_true')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as directory:
        kfp.Client._LOCAL_KFP_CONTEXT = str(Path(directory) / 'context.json')
        client = kfp.Client(
            kube_context=args.context,
            namespace=args.namespace,
            healthz_max_attempts=1,
            existing_token=os.environ['KFP_TEST_TOKEN']
            if args.service_account_token
            else None,
        )
        try:
            response = client.list_experiments(namespace=args.namespace)
        except kfp.server_api.ApiException as error:
            raise SystemExit(
                f'Native authentication failed: {error.status} {error.reason}'
            ) from None
        print(f'Experiment listing succeeded: {response.total_size}')
        if args.run:
            from sample_corpus import ROOT, definitions

            source = ROOT / 'samples/core/execution_order/execution_order.py'
            definitions_, _, error = definitions(source, source.read_text())
            assert error is None, error
            result = client.create_run_from_pipeline_func(
                definitions_['execution_order_pipeline'],
                arguments={},
                run_name='Direct Kubernetes SDK authentication',
                experiment_name='Direct Kubernetes SDK compatibility',
                namespace=args.namespace,
            )
            completed = result.wait_for_run_completion(timeout=300)
            assert completed.state == 'SUCCEEDED', completed.state
            print(f'Unchanged sample succeeded: {result.run_id}')
