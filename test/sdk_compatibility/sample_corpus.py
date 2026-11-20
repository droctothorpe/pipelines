# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Compile unchanged sample DSL definitions without running submission cells.

Pipeline/component bodies are never rewritten. Notebook install/magic lines and
script submission/timing cells are not part of the compile-only pass. Runtime
acceptance is a separate stage; compilation is not evidence of execution.
"""

import argparse
import ast
import hashlib
import json
import linecache
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def sources():
    for path in sorted((ROOT / 'samples').rglob('*')):
        if 'argo-native' in path.parts or path.name.endswith('_test.py'):
            continue
        if path.suffix == '.py':
            yield path, path.read_text()
        elif path.suffix == '.ipynb':
            cells = json.loads(path.read_text()).get('cells', [])
            text = '\n\n'.join(
                ''.join(cell['source'])
                for cell in cells
                if cell['cell_type'] == 'code'
            )
            yield (
                path,
                '\n'.join(
                    '' if line.lstrip().startswith(('!', '%')) else line
                    for line in text.splitlines()
                ),
            )


def definitions(path, source):
    """Preserve original source/line numbers for inspect.getsource in decorators."""
    tree = ast.parse(source, filename=str(path))
    names = [
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and any(
            ast.unparse(decorator).split('(')[0].split('.')[-1] == 'pipeline'
            for decorator in node.decorator_list
        )
    ]
    if not names:
        return {}, [], None
    allowed = (
        ast.Import,
        ast.ImportFrom,
        ast.FunctionDef,
        ast.ClassDef,
        ast.Assign,
        ast.AnnAssign,
    )
    body = []
    for node in tree.body:
        if not isinstance(node, allowed):
            continue
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and any(
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and (
                call.func.attr == 'Client'
                or call.func.attr.startswith(('create_run_', 'wait_for_run_'))
            )
            for call in ast.walk(node)
        ):
            continue
        body.append(node)
    tree.body = body
    name = (
        '_stock_sample_' + hashlib.sha256(str(path).encode()).hexdigest()[:16]
    )
    module = types.ModuleType(name)
    module.__file__ = str(path)
    sys.modules[name] = module
    linecache.cache[str(path)] = (
        len(source),
        None,
        source.splitlines(keepends=True),
        str(path),
    )
    try:
        exec(compile(tree, str(path), 'exec'), module.__dict__)
        error = None
    except Exception as exc:
        error = f'{type(exc).__name__}: {exc}'
    return module.__dict__, names, error


def compile_samples(output):
    from kfp import compiler

    output.mkdir(parents=True, exist_ok=True)
    report = []
    for path, source in sources():
        namespace, names, load_error = definitions(path, source)
        for name in names:
            row = {
                'source': str(path.relative_to(ROOT)),
                'pipeline': name,
                'execution': 'not_run',
            }
            if name not in namespace:
                row.update(compile='failed', error=load_error)
            else:
                target = output / (
                    hashlib.sha256(str(path).encode()).hexdigest()[:12]
                    + '-'
                    + name
                    + '.yaml'
                )
                try:
                    compiler.Compiler().compile(namespace[name], str(target))
                    row.update(compile='passed', manifest=str(target))
                except Exception as error:
                    row.update(
                        compile='failed',
                        error=f'{type(error).__name__}: {error}',
                    )
            report.append(row)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    rows = compile_samples(args.output.resolve())
    (args.output / 'report.json').write_text(json.dumps(rows, indent=2))
    for row in rows:
        print(
            row['compile'].upper(),
            row['source'] + ':' + row['pipeline'],
            row.get('error', ''),
        )
    failed = sum(row['compile'] == 'failed' for row in rows)
    print(
        f'{len(rows) - failed}/{len(rows)} sample DSL definitions compiled; execution not assessed.'
    )
    raise SystemExit(bool(failed))
