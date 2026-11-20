# Copyright 2026 The Kubeflow Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""In-container adapter for Argo-staged files.

No service or storage client.
"""

import inspect
import json
import math
import os
import sys
from contextlib import nullcontext
from functools import wraps
from pathlib import Path
from typing import Callable

from kfp.dsl.executor import Executor

SCHEMA = 'kfp-argo/v1'


def serialize(value, parameter_type: str) -> str:
    """Serialize an Argo parameter without losing its declared Python type."""
    if parameter_type.startswith('Nullable'):
        base = parameter_type.removeprefix('Nullable')
        if value is None:
            return 'null'
        serialize(value, base)
        return json.dumps(value, allow_nan=False, separators=(',', ':'))
    if parameter_type == 'String':
        if not isinstance(value, str):
            raise ValueError('Expected a String parameter; supply a string.')
        return value
    encoded = json.dumps(value, allow_nan=False, separators=(',', ':'))
    deserialize(encoded, parameter_type)
    return encoded


def deserialize(value: str, parameter_type: str):
    """Read an Argo string parameter and validate the declared scalar type."""
    if parameter_type.startswith('Nullable'):
        result = json.loads(value)
        if result is None:
            return None
        base = parameter_type.removeprefix('Nullable')
        serialize(result, base)
        return result
    if parameter_type == 'String':
        return value
    result = json.loads(value)
    # Reject non-finite numbers inside collections as well as scalar values.
    json.dumps(result, allow_nan=False)
    expected = {
        'Integer': int,
        'Float': (int, float),
        'Boolean': bool,
        'List': list,
        'Dict': dict,
    }.get(parameter_type)
    if expected is None:
        raise ValueError(
            f'Unsupported parameter type {parameter_type!r}; use a JSON scalar, list or dict.'
        )
    if (
        not isinstance(result, expected)
        or (parameter_type in ('Integer', 'Float') and isinstance(result, bool))
        or (isinstance(result, float) and not math.isfinite(result))
    ):
        raise ValueError(f'Expected {parameter_type}, received {value!r}.')
    return result


def deserialize_collection(value: str, element_type: str, depth: int):
    """Restore Python values from Argo's nested arrays of parameter strings."""
    if depth < 1:
        raise ValueError(
            'Collected inputs must cross at least one ParallelFor scope.'
        )
    items = deserialize(value, 'List')
    return [
        deserialize_collection(
            item if isinstance(item, str) else json.dumps(item),
            element_type,
            depth - 1,
        )
        if depth > 1
        else deserialize(
            item if isinstance(item, str) else json.dumps(item), element_type
        )
        for item in items
    ]


def resolve_task_config(value, parameters, workflow_name=None):
    def resolve(item):
        if isinstance(item, dict):
            markers = {
                '__kfp_native_json__',
                '__kfp_native_claims__',
                '__kfp_native_claim_refs__',
            }
            if len(item) == 1 and next(iter(item)) in markers:
                marker = next(iter(item))
                resolved = json.loads(parameters[item[marker]])
                json.dumps(resolved, allow_nan=False)
                if marker == '__kfp_native_json__':
                    if not isinstance(resolved, dict):
                        raise ValueError(
                            'Structured TaskConfig settings require a JSON object.'
                        )
                    return resolved
                claims = resolved if isinstance(resolved, list) else [resolved]
                names, output = set(), []
                for claim in claims:
                    name = (
                        claim.get('resourceClaimTemplateName')
                        if isinstance(claim, dict)
                        else None
                    )
                    if not isinstance(name, str) or not name:
                        raise ValueError(
                            'Resource claims require resourceClaimTemplateName.'
                        )
                    if name in names:
                        raise ValueError('Duplicate resource claim name.')
                    names.add(name)
                    output.append(
                        {**claim, 'name': name}
                        if marker == '__kfp_native_claims__'
                        else {'name': name}
                    )
                return output or None
            return {key: resolve(entry) for key, entry in item.items()}
        if isinstance(item, list):
            return [resolve(entry) for entry in item]
        return item

    result = resolve(value)
    workspace = result.pop('__kfp_workspace__', None)
    if workspace and any(
        '/kfp-workspace' in parameters.get(name, '')
        for name in workspace['strings']
    ):
        workflow_name = workflow_name or os.environ.get(
            'KFP_ARGO_WORKFLOW_NAME'
        )
        if not workflow_name:
            raise ValueError('Workspace TaskConfig requires workflow identity.')
        result['volumes'] = (result.get('volumes') or []) + [
            {
                'name': 'kfp-workspace',
                'persistentVolumeClaim': {
                    'claimName': workflow_name + '-kfp-workspace'
                },
            }
        ]
        result['volumeMounts'] = (result.get('volumeMounts') or []) + [
            {'name': 'kfp-workspace', 'mountPath': '/kfp-workspace'}
        ]
    return result


def _with_task_configs(function, configurations):
    @wraps(function)
    def invoke(*args, **kwargs):
        for name, config in configurations.items():
            value = kwargs.get(name)
            if value is None:
                continue
            for attribute, key in [
                ('affinity', 'affinity'),
                ('tolerations', 'tolerations'),
                ('node_selector', 'nodeSelector'),
                ('env', 'env'),
                ('volumes', 'volumes'),
                ('volume_mounts', 'volumeMounts'),
                ('resources', 'resources'),
                ('resource_claims', 'resourceClaims'),
            ]:
                setattr(value, attribute, config.get(key))
        return function(*args, **kwargs)

    invoke.__signature__ = inspect.signature(function)
    return invoke


def _write(path: str, value: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(value)


class _StagedExecutor(Executor):
    def make_artifact(self, runtime_artifact, name, func, annotation=None):
        artifact = super().make_artifact(
            runtime_artifact, name, func, annotation
        )
        artifact.custom_path = runtime_artifact['path']
        return artifact


def execute(function: Callable, contract: dict, parameters: list[dict]) -> dict:
    """Invoke an unchanged KFP function against Argo input/output declarations.

    The contract is static component configuration. Argo supplies
    parameter values separately, so quotes in user values cannot alter
    its structure. Each input artifact has a staged payload and a staged
    metadata companion. Output storage URIs must match the artifact
    repository's configured key.
    """
    if contract.get('schema') != SCHEMA:
        raise ValueError(
            f'Unsupported Argo runtime contract; expected {SCHEMA}.'
        )
    values = {entry['name']: entry['value'] for entry in parameters}
    inputs = {'parameterValues': {}, 'artifacts': {}}
    references = []
    staged_lists = None
    for name, port in contract.get('inputs', {}).items():
        if port.get('artifactList') or port.get('stagedArtifact'):
            if staged_lists is None:
                staged_lists = json.loads(
                    Path(port['manifestPath']).read_text()
                )
                if staged_lists.get('schema') != SCHEMA:
                    raise ValueError(
                        'Unsupported staged artifact-list manifest.'
                    )
            artifacts = []
            entries = staged_lists['inputs'][name]
            if port.get('stagedArtifact') and len(entries) != 1:
                raise ValueError(
                    'Artifact iteration requires exactly one staged input.'
                )
            for index, entry in enumerate(entries):
                metadata = entry['identity']
                if 'metadataPath' in entry:
                    metadata = json.loads(
                        Path(entry['metadataPath']).read_text()
                    )
                    if any(
                        metadata.get(key) != entry['identity'].get(key)
                        for key in ('schema', 'port', 'type', 'producer', 'uri')
                    ):
                        raise ValueError(
                            f'Artifact metadata identity mismatch for collection {name!r}.'
                        )
                if metadata.get('schema') != SCHEMA or (
                    port['type'] != 'system.Artifact@0.0.1'
                    and metadata['type'] != port['type']
                ):
                    raise ValueError(
                        f'Artifact type mismatch for collection {name!r}.'
                    )
                references.append(
                    {
                        'port': name
                        if port.get('stagedArtifact')
                        else f'{name}[{index}]',
                        'producer': metadata['producer'],
                        'uri': metadata['uri'],
                    }
                )
                artifacts.append(
                    {
                        'name': metadata['port'],
                        'uri': metadata['uri'],
                        'metadata': metadata['metadata'],
                        'path': entry['path'],
                        'type': {'schemaTitle': metadata['type'].split('@')[0]},
                    }
                )
            inputs['artifacts'][name] = {'artifacts': artifacts}
            continue
        if 'presenceParameter' in port:
            if not deserialize(values[port['presenceParameter']], 'Boolean'):
                continue
        if 'path' not in port:
            if name in values:
                if 'collectionElementType' in port:
                    inputs['parameterValues'][name] = deserialize_collection(
                        values[name],
                        port['collectionElementType'],
                        port['collectionDepth'],
                    )
                else:
                    inputs['parameterValues'][name] = deserialize(
                        values[name], port['type']
                    )
            elif not port.get('optional'):
                raise ValueError(
                    f'Missing required parameter {name!r}; pass it to Argo.'
                )
            if port.get('taskConfig') and name in inputs['parameterValues']:
                inputs['parameterValues'][name] = resolve_task_config(
                    inputs['parameterValues'][name], values
                )
            continue
        metadata_path = Path(port['metadataPath'])
        if metadata_path.exists():
            metadata = json.loads(metadata_path.read_text())
        else:
            metadata = json.loads(values.get('kfp-meta-' + name, '{}'))
            if 'metadata' not in metadata:
                raise ValueError(
                    f'Artifact metadata unavailable for {name!r}; restore the producer metadata artifact before retrying.'
                )
        if metadata.get('schema') != SCHEMA:
            raise ValueError(
                f'Unsupported metadata for input {name!r}; regenerate its producer.'
            )
        if (
            metadata['type'] != port['type']
            and port['type'] != 'system.Artifact@0.0.1'
        ):
            raise ValueError(f'Artifact type mismatch for {name!r}.')
        references.append(
            {
                'port': name,
                'producer': metadata['producer'],
                'uri': metadata['uri'],
            }
        )
        inputs['artifacts'][name] = {
            'artifacts': [
                {
                    'name': metadata['port'],
                    'uri': metadata['uri'],
                    'metadata': metadata['metadata'],
                    'path': port['path'],
                    'type': {'schemaTitle': metadata['type'].split('@')[0]},
                }
            ]
        }
    root = contract['outputDirectory']
    producer = {
        'run': os.environ['KFP_ARGO_RUN_UID'],
        'task': os.environ['KFP_ARGO_NODE_ID'],
        'namespace': os.environ['KFP_ARGO_NAMESPACE'],
    }
    outputs = {
        'outputFile': f'{root}/executor.json',
        'parameters': {},
        'artifacts': {},
    }
    for name, port in contract.get('outputs', {}).items():
        if 'metadataPath' not in port:
            outputs['parameters'][name] = {'outputFile': port['path']}
        else:
            uri = (
                port['uri']
                .replace('{run}', producer['run'])
                .replace('{task}', producer['task'])
            )
            outputs['artifacts'][name] = {
                'artifacts': [
                    {
                        'name': name,
                        'uri': uri,
                        'path': port['path'],
                        'type': {'schemaTitle': port['type'].split('@')[0]},
                    }
                ]
            }
    options = {}
    if 'artifact_previews' in inspect.signature(_StagedExecutor).parameters:
        options['artifact_previews'] = False
    configurations = {
        name: inputs['parameterValues'].get(name, {})
        for name, port in contract.get('inputs', {}).items()
        if port.get('taskConfig')
    }
    if configurations:
        function = _with_task_configs(function, configurations)
    executor = _StagedExecutor(
        {'inputs': inputs, 'outputs': outputs}, function, **options
    )
    for name, port in contract.get('inputs', {}).items():
        if (
            port.get('artifactList')
            and not inputs['artifacts'][name]['artifacts']
        ):
            executor.input_artifacts[name] = []
    previews = None
    if executor.output_artifacts and contract.get('artifactPreviews', True):
        preview_module = sys.modules.get('_kfp_native_artifact_preview')
        if preview_module is None:
            from kfp.dsl import _artifact_preview as preview_module
        previews = preview_module.ArtifactPreviewSession(
            executor.output_artifacts
        )
    with previews if previews is not None else nullcontext():
        try:
            output = executor.execute()
        except SystemExit as error:
            if error.code not in (None, 0):
                raise
            # sys.exit(0) is successful completion, not permission to omit metadata.
            output = executor.write_executor_output()
        if output is not None and previews is not None:
            previews.generate()
    if output is None:
        raise RuntimeError(
            'Argo components require one output-writing process per task.'
        )
    summary = {
        'schema': SCHEMA,
        'producer': producer,
        'inputs': references,
        'artifacts': [],
        'metrics': {},
    }
    for name, port in contract.get('outputs', {}).items():
        if 'metadataPath' not in port:
            if name in executor.excutor_output.get('parameterValues', {}):
                _write(
                    port['path'],
                    serialize(
                        executor.excutor_output['parameterValues'][name],
                        port['type'],
                    ),
                )
            else:
                # Stock OutputPath(bool) accepts str(True)/str(False), not only JSON.
                value = Path(port['path']).read_text()
                if port['type'] == 'Boolean' and value.strip() in (
                    'True',
                    'False',
                ):
                    value = value.strip().lower()
                    _write(port['path'], value)
                deserialize(value, port['type'])
            continue
        artifact = executor.output_artifacts[name]
        if (
            artifact.path != port['path']
            or artifact.uri != outputs['artifacts'][name]['artifacts'][0]['uri']
        ):
            raise ValueError(
                f'Output {name!r} changed its assigned path or URI; write to the supplied artifact.path.'
            )
        metadata = {
            'schema': SCHEMA,
            'port': name,
            'type': port['type'],
            'producer': producer,
            'uri': artifact.uri,
            'metadata': artifact.metadata,
            'inputs': references,
        }
        if port['type'].startswith('system.Metrics@'):
            summary['metrics'].update(artifact.metadata)
        if port['type'].split('@', 1)[0] in (
            'system.Metrics',
            'system.ClassificationMetrics',
            'system.SlicedClassificationMetrics',
        ):
            # Metrics have metadata but need not write a payload themselves.
            if not Path(artifact.path).exists():
                _write(
                    artifact.path,
                    json.dumps(artifact.metadata, allow_nan=False),
                )
        if not Path(artifact.path).exists():
            raise ValueError(
                f'Output artifact {name!r} was not written to {artifact.path}.'
            )
        _write(port['metadataPath'], json.dumps(metadata, allow_nan=False))
        if 'identityPath' in port:
            identity = {
                key: metadata[key]
                for key in ('schema', 'port', 'type', 'producer', 'uri')
            }
            if port.get('metadataUri'):
                identity['metadataUri'] = (
                    port['metadataUri']
                    .replace('{run}', producer['run'])
                    .replace('{task}', producer['task'])
                )
            _write(port['identityPath'], json.dumps(identity, allow_nan=False))
        summary['artifacts'].append(metadata)
    _write(f'{root}/metadata.json', json.dumps(summary, allow_nan=False))
    return summary


def main():
    """Run the embedded bridge with the ordinary SDK component-loader arguments."""
    import argparse
    import logging
    import sys

    from kfp.dsl import kfp_config, utils

    logging.basicConfig(
        stream=sys.stdout,
        level=logging.INFO,
        format='[KFP Executor %(asctime)s %(levelname)s]: %(message)s',
    )
    parser = argparse.ArgumentParser(description='KFP component executor')
    parser.add_argument('--component_module_path')
    parser.add_argument('--function_to_execute', required=True)
    parser.add_argument('--argo_input', required=True)
    parser.add_argument('--argo_parameters', default='[]')
    parser.add_argument('--argo_parameters_file')
    args, _ = parser.parse_known_args()
    if args.component_module_path:
        path = Path(args.component_module_path)
    else:
        components = kfp_config.KFPConfig().get_components()
        if args.function_to_execute not in components:
            raise RuntimeError(
                f'Could not find component {args.function_to_execute!r} in kfp_config.ini.'
            )
        path = Path(components[args.function_to_execute])
    logging.info(
        'Looking for component `%s` in %s', args.function_to_execute, path
    )
    module = utils.load_module(
        module_name=path.stem, module_directory=str(path.parent)
    )
    execute(
        getattr(module, args.function_to_execute),
        json.loads(args.argo_input),
        json.loads(Path(args.argo_parameters_file).read_text())
        if args.argo_parameters_file
        else json.loads(args.argo_parameters),
    )


if __name__ == '__main__':
    main()
