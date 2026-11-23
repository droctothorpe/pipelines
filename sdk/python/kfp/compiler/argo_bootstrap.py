# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Embed the native bridge without changing user component images or source."""

import base64
import re
import shlex
import zlib
from pathlib import Path

from kfp.dsl import argo_runtime

EXECUTOR = 'kfp.dsl.executor_main'


def portable_command(command, artifact_previews=True):
    """Replace SDK executor invocations, leaving install scripts and user code
    intact."""
    source = Path(argo_runtime.__file__).read_bytes()
    encoded = base64.b64encode(zlib.compress(source)).decode('ascii')
    # Older SDK module loaders assume importlib.util was imported by their entrypoint.
    bootstrap = 'import base64,zlib,importlib.util;'
    if artifact_previews:
        preview = (
            Path(argo_runtime.__file__)
            .with_name('_artifact_preview.py')
            .read_bytes()
        )
        preview = base64.b64encode(zlib.compress(preview)).decode('ascii')
        bootstrap += (
            "import sys,types;_preview=types.ModuleType('_kfp_native_artifact_preview');"
            'sys.modules[_preview.__name__]=_preview;'
            f"exec(compile(zlib.decompress(base64.b64decode({preview!r})), '<kfp-native-preview>', 'exec'),_preview.__dict__);"
        )
    bootstrap += (
        f'exec(compile(zlib.decompress(base64.b64decode({encoded!r})), '
        "'<kfp-native-runtime>', 'exec'))"
    )
    result = list(command or [])
    replaced = False
    for index in range(len(result) - 1):
        if result[index : index + 2] == ['-m', EXECUTOR]:
            result[index : index + 2] = ['-c', bootstrap]
            replaced = True
    pattern = re.compile(
        r'\b(python(?:3(?:\.\d+)?)?)\s+-m\s+kfp\.dsl\.executor_main\b'
    )
    for index, value in enumerate(result):
        # Only inspect shell programs, never the following positional argument
        # containing the user's function source.
        if (
            index >= 2
            and result[index - 1] in ('-c', '-ec')
            and result[index - 2] in ('sh', 'bash', '/bin/sh', '/bin/bash')
        ):
            value, count = pattern.subn(
                lambda match: match[1] + ' -c ' + shlex.quote(bootstrap), value
            )
            result[index] = value
            replaced = replaced or bool(count)
    if not replaced:
        raise ValueError(
            'Python component command has no supported SDK executor invocation.'
        )
    return result
