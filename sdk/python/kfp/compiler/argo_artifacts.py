# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Native artifact locations parameterized by Workflow metadata."""

import re
from urllib.parse import urlsplit

ROOT = 'pipelines.kubeflow.org/artifact-repository'
BUCKET = 'pipelines.kubeflow.org/artifact-bucket'
PREFIX = 'pipelines.kubeflow.org/artifact-key-prefix'
BINDING = 'pipelines.kubeflow.org/artifact-root-binding'
ROOT_KEYS = (ROOT, BUCKET, PREFIX, BINDING)


def reference(annotation):
    # Simple tags retain dotted annotation keys; expression maps split dots.
    return '{{workflow.annotations.' + annotation + '}}'


def root_annotations(root):
    location = urlsplit(root)
    if (
        location.scheme not in ('s3', 'gs')
        or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', location.netloc)
        or location.query
        or location.fragment
    ):
        raise ValueError(
            'Pipeline artifact roots must be s3://bucket[/prefix] or gs://bucket[/prefix].'
        )
    prefix = location.path.strip('/')
    return {
        ROOT: root.rstrip('/'),
        BUCKET: location.netloc,
        PREFIX: prefix + '/' if prefix else '',
        BINDING: 'v1',
    }


def override_root(manifest, root):
    """Change only compiler-owned artifact bindings, never user strings."""
    annotations = manifest.setdefault('metadata', {}).setdefault(
        'annotations', {}
    )
    values = root_annotations(root)
    if annotations.get(ROOT, '').rstrip('/') == values[ROOT]:
        return
    if annotations.get(BINDING) != 'v1':
        raise ValueError(
            'This package lacks artifact-root bindings. Recompile its Python source before overriding pipeline_root.'
        )
    driver = 's3' if root.startswith('s3:') else 'gcs'
    spec = manifest['spec']
    if manifest['kind'] == 'CronWorkflow':
        spec = spec['workflowSpec']
    for template in spec.get('templates', []):
        for artifact in template.get('outputs', {}).get('artifacts', []):
            for previous in ('s3', 'gcs'):
                location = artifact.get(previous, {})
                if previous != driver and location.get('bucket') == reference(
                    BUCKET
                ):
                    if location.keys() - {'bucket', 'key'}:
                        raise ValueError(
                            'Cannot change artifact storage scheme with explicit driver credentials/settings. Recompile for the new storage scheme.'
                        )
                    artifact[driver] = artifact.pop(previous)
    annotations.update(values)
