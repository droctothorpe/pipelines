# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Read native pipeline packages through the SDK's existing file interfaces."""

import copy
import dataclasses
import hashlib
import json
import tarfile
import zipfile
from pathlib import Path

import yaml

MAX_PACKAGE_BYTES = 64 * 1024 * 1024


@dataclasses.dataclass
class PipelineDocument:
    pipeline_spec: dict

    @property
    def name(self):
        metadata = self.pipeline_spec.get('metadata', {})
        return (
            metadata.get('annotations', {}).get(
                'pipelines.kubeflow.org/display-name'
            )
            or metadata.get('labels', {}).get('pipelines.kubeflow.org/pipeline')
            or metadata.get('name')
            or metadata.get('generateName', '').rstrip('-')
        )

    def to_dict(self):
        return copy.deepcopy(self.pipeline_spec)


def _choose_file(names):
    candidates = [
        name for name in names if name.endswith(('.yaml', '.yml', '.json'))
    ]
    for preferred in ('pipeline.yaml', 'pipeline.yml', 'pipeline.json'):
        if preferred in candidates:
            return preferred
    if len(candidates) == 1:
        return candidates[0]
    raise ValueError(
        'Invalid package. Include one pipeline YAML/JSON file or name it pipeline.yaml.'
    )


def _read(stream):
    content = stream.read(MAX_PACKAGE_BYTES + 1)
    if len(content) > MAX_PACKAGE_BYTES:
        raise ValueError(
            'Pipeline package exceeds the 64 MiB uncompressed safety limit.'
        )
    documents = [
        document
        for document in yaml.safe_load_all(content)
        if document is not None
    ]
    if len(documents) != 1 or not isinstance(documents[0], dict):
        raise ValueError(
            'A native pipeline package must contain exactly one Argo manifest.'
        )
    manifest = documents[0]
    if manifest.get('apiVersion') != 'argoproj.io/v1alpha1' or manifest.get(
        'kind'
    ) not in ('WorkflowTemplate', 'Workflow', 'CronWorkflow'):
        raise ValueError(
            'Expected a compiled native Argo pipeline. Recompile historical KFP IR from its Python source.'
        )
    spec = manifest.get('spec')
    if not isinstance(spec, dict):
        raise ValueError('The native pipeline manifest is missing its spec.')
    if manifest['kind'] == 'CronWorkflow':
        spec = spec.get('workflowSpec', {})
    if not spec.get('templates') or not spec.get('entrypoint'):
        raise ValueError(
            'A pipeline package must include its native templates and entrypoint.'
        )
    # Reject non-JSON YAML values before passing the manifest to a resource API.
    json.dumps(manifest, allow_nan=False)
    return PipelineDocument(manifest)


def override_caching(manifest, enable_caching, cache_key=None):
    """Apply existing run-level cache overrides without mutating a stored
    version."""
    spec = manifest['spec']
    if manifest['kind'] == 'CronWorkflow':
        spec = spec['workflowSpec']
    templates = {template['name']: template for template in spec['templates']}
    root = templates[spec['entrypoint']]
    direct = {task['template'] for task in root.get('dag', {}).get('tasks', [])}
    if 'container' in root:
        direct.add(root['name'])
    for template in templates.values():
        if 'container' not in template:
            continue
        encoded = (
            template.get('metadata', {})
            .get('annotations', {})
            .get('pipelines.kubeflow.org/cache-policy')
        )
        policy = json.loads(encoded) if encoded else None
        if enable_caching is False:
            template.pop('memoize', None)
            continue
        if enable_caching is True and 'memoize' not in template:
            if not policy:
                raise ValueError(
                    'This package lacks cache-override metadata. Recompile its Python source with this SDK.'
                )
            template['memoize'] = copy.deepcopy(policy['memoize'])
        if cache_key and template['name'] in direct and 'memoize' in template:
            if not policy:
                raise ValueError(
                    'This package lacks component cache identity. Recompile its Python source with this SDK.'
                )
            template['memoize']['key'] = hashlib.sha256(
                (policy['component'] + '\0' + cache_key).encode()
            ).hexdigest()


def extract_pipeline(package_file):
    name = str(package_file)
    if name.endswith(('.tar.gz', '.tgz')):
        with tarfile.open(name, 'r:gz') as archive:
            member = _choose_file(
                [item.name for item in archive if item.isfile()]
            )
            with archive.extractfile(archive.getmember(member)) as stream:
                return _read(stream)
    if name.endswith('.zip'):
        with zipfile.ZipFile(name) as archive:
            member = _choose_file(
                [
                    item.filename
                    for item in archive.infolist()
                    if not item.is_dir()
                ]
            )
            with archive.open(member) as stream:
                return _read(stream)
    if name.endswith(('.yaml', '.yml', '.json')):
        with Path(name).open('rb') as stream:
            return _read(stream)
    raise ValueError(
        'Pipeline packages must end in .yaml, .yml, .json, .zip, .tar.gz or .tgz.'
    )
