# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Two-environment runtime check: prepare with this SDK, run with stock KFP.

``test_stock_runtime.py`` drives both halves. By hand:

uv run python test/e2e/stock_runtime.py prepare /tmp/kfp-stock-runtime
uv run --no-project --python 3.11 --with kfp==2.17.0 python -I \
    test/e2e/stock_runtime.py run /tmp/kfp-stock-runtime

The ``run`` half imports only ``kfp`` so it can execute under the unmodified
PyPI release; keep this module free of suite imports.
"""

import argparse
import importlib.util
import json
import os
import subprocess
from pathlib import Path


def prepare(root):
    from kfp.compiler.argo_bootstrap import portable_command

    root.mkdir(parents=True, exist_ok=True)
    component = root / 'component.py'
    component.write_text(
        'from kfp.dsl import Dataset, Output\n\n'
        'def produce(value: int, dataset: Output[Dataset]) -> int:\n'
        '    from pathlib import Path\n'
        "    Path(dataset.path).write_text('payload:' + str(value))\n"
        "    dataset.metadata['rows'] = value\n"
        '    return value + 1\n'
    )
    contract = {
        'schema': 'kfp-argo/v1',
        'outputDirectory': str(root),
        'inputs': {'value': {'type': 'Integer'}},
        'outputs': {
            'Output': {'type': 'Integer', 'path': str(root / 'result')},
            'dataset': {
                'type': 'system.Dataset@0.0.1',
                'path': str(root / 'dataset'),
                'metadataPath': str(root / 'dataset.json'),
                'identityPath': str(root / 'identity.json'),
                'uri': 's3://bucket/{run}/{task}/dataset',
            },
        },
    }
    command = portable_command(['python3', '-m', 'kfp.dsl.executor_main']) + [
        '--component_module_path',
        str(component),
        '--function_to_execute',
        'produce',
        '--argo_input',
        json.dumps(contract),
        '--argo_parameters',
        '[{"name":"value","value":"7"}]',
    ]
    (root / 'command.json').write_text(json.dumps(command))


def run(root):
    import kfp

    assert importlib.util.find_spec('kfp.dsl.argo_runtime') is None, (
        kfp.__file__
    )
    command = json.loads((root / 'command.json').read_text())
    result = subprocess.run(
        command,
        env={
            **os.environ,
            '_KFP_RUNTIME': 'true',
            'KFP_ARGO_RUN_UID': 'run',
            'KFP_ARGO_NODE_ID': 'task',
            'KFP_ARGO_NAMESPACE': 'team',
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert (root / 'result').read_text() == '8'
    assert (root / 'dataset').read_text() == 'payload:7'
    metadata = json.loads((root / 'dataset.json').read_text())
    assert metadata['metadata']['rows'] == 7
    assert metadata['uri'] == 's3://bucket/run/task/dataset'
    print(
        f'Passed with unmodified KFP {kfp.__version__}: parameter, artifact, metadata and URI.'
    )


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'run'])
    parser.add_argument('directory', type=Path)
    options = parser.parse_args()
    (prepare if options.action == 'prepare' else run)(
        options.directory.resolve()
    )
