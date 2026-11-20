#!/usr/bin/env python3
# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Capture public calling conventions from a fixed stock SDK revision.

This records source facts, not native expectations. Regenerate only when
changing an explicitly agreed reference revision, never to make
compatibility tests pass.
"""

import argparse
import ast
import json
import subprocess
from pathlib import Path

BASELINE = '7780f12acfbde9f16169c7fcbfdfb6c3ef5432ea'
TARGETS = {
    'sdk/python/kfp/client/client.py': ['Client', 'RunPipelineResult'],
    'sdk/python/kfp/compiler/compiler.py': ['Compiler'],
    'sdk/python/kfp/dsl/pipeline_task.py': ['PipelineTask'],
    'sdk/python/kfp/dsl/component_decorator.py': ['component'],
    'sdk/python/kfp/dsl/container_component_decorator.py': [
        'container_component'
    ],
    'sdk/python/kfp/dsl/notebook_component_decorator.py': [
        'notebook_component'
    ],
    'sdk/python/kfp/dsl/pipeline_context.py': ['pipeline'],
}


def parameters(function):
    args = function.args
    positional = [*args.posonlyargs, *args.args]
    defaults = [None] * (len(positional) - len(args.defaults)) + args.defaults
    result = []
    for i, (arg, default) in enumerate(zip(positional, defaults)):
        result.append(
            {
                'name': arg.arg,
                'kind': 'POSITIONAL_ONLY'
                if i < len(args.posonlyargs)
                else 'POSITIONAL_OR_KEYWORD',
                'default': ast.unparse(default)
                if default is not None
                else None,
            }
        )
    if args.vararg:
        result.append(
            {'name': args.vararg.arg, 'kind': 'VAR_POSITIONAL', 'default': None}
        )
    for arg, default in zip(args.kwonlyargs, args.kw_defaults):
        result.append(
            {
                'name': arg.arg,
                'kind': 'KEYWORD_ONLY',
                'default': ast.unparse(default)
                if default is not None
                else None,
            }
        )
    if args.kwarg:
        result.append(
            {'name': args.kwarg.arg, 'kind': 'VAR_KEYWORD', 'default': None}
        )
    return result


def capture(ref):
    result = {}
    for path, names in TARGETS.items():
        source = subprocess.check_output(
            ['git', 'show', f'{ref}:{path}'], text=True
        )
        module = ast.parse(source)
        prefix = (
            path.removeprefix('sdk/python/')
            .removesuffix('.py')
            .replace('/', '.')
        )
        for item in module.body:
            if (
                not isinstance(item, (ast.ClassDef, ast.FunctionDef))
                or item.name not in names
            ):
                continue
            if isinstance(item, ast.FunctionDef):
                result[f'{prefix}:{item.name}'] = parameters(item)
            else:
                for method in item.body:
                    if isinstance(method, ast.FunctionDef) and (
                        not method.name.startswith('_')
                        or method.name == '__init__'
                    ):
                        if any(
                            isinstance(decorator, ast.Name)
                            and decorator.id == 'property'
                            for decorator in method.decorator_list
                        ):
                            continue
                        result[f'{prefix}:{item.name}.{method.name}'] = (
                            parameters(method)
                        )
    return {'baseline': ref, 'contracts': result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ref', default=BASELINE)
    parser.add_argument(
        '--output',
        type=Path,
        default=Path('test/data/stock_signatures.json'),
    )
    options = parser.parse_args()
    result = capture(options.ref)
    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + '\n'
    )
    print(
        f'Captured {len(result["contracts"])} calling conventions from {options.ref}.'
    )


if __name__ == '__main__':
    main()
