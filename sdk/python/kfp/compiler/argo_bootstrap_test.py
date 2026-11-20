# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0

import json
import os
import subprocess
import sys

from kfp.compiler.argo_bootstrap import portable_command


def test_direct_executor_command_runs_without_importing_fork_bridge(tmp_path):
    component = tmp_path / 'component.py'
    component.write_text('def echo(value: int) -> int:\n    return value\n')
    output = tmp_path / 'result'
    contract = {
        'schema': 'kfp-argo/v1',
        'outputDirectory': str(tmp_path),
        'inputs': {'value': {'type': 'Integer'}},
        'outputs': {'Output': {'type': 'Integer', 'path': str(output)}},
    }
    command = portable_command([sys.executable, '-m', 'kfp.dsl.executor_main'])
    command[2] = (
        "import sys;sys.modules['kfp.dsl.argo_runtime']=None;" + command[2]
    )
    command += [
        '--component_module_path',
        str(component),
        '--function_to_execute',
        'echo',
        '--argo_input',
        json.dumps(contract),
        '--argo_parameters',
        '[{"name":"value","value":"7"}]',
    ]
    environment = {
        **os.environ,
        '_KFP_RUNTIME': 'true',
        'KFP_ARGO_RUN_UID': 'run',
        'KFP_ARGO_NODE_ID': 'task',
        'KFP_ARGO_NAMESPACE': 'team',
    }
    result = subprocess.run(
        command, env=environment, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert output.read_text() == '7'
    assert (
        json.loads((tmp_path / 'metadata.json').read_text())['producer']['run']
        == 'run'
    )


def test_shell_rewrite_preserves_user_source_and_install_wrapper():
    source = "def component():\n    return 'python3 -m kfp.dsl.executor_main'\n"
    command = [
        'sh',
        '-c',
        'install-packages; "$0" "$@"',
        'sh',
        '-ec',
        'python3 -m kfp.dsl.executor_main "$@"',
        source,
    ]
    rewritten = portable_command(command)
    assert rewritten[:5] == command[:5]
    assert rewritten[-1] == source
    assert 'python3 -c ' in rewritten[5]
    assert 'python3 -m kfp.dsl.executor_main' not in rewritten[5]
