# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Native artifact locations parameterized by Workflow metadata.

Compiled artifacts carry only a key. Argo places them in the artifact repository
it resolves for the run's namespace (``artifact-repositories`` ConfigMap, else
the controller default), which is the namespace storage policy stock KFP kept
in its ``kfp-launcher`` ConfigMap. The bucket behind that repository is bound
into the run's annotations when it is submitted, so URIs stay static for raw
containers and importers; an explicit ``pipeline_root`` selects the repository
entry that serves its bucket.
"""

import re
from urllib.parse import urlsplit

ROOT = 'pipelines.kubeflow.org/artifact-repository'
BUCKET = 'pipelines.kubeflow.org/artifact-bucket'
PREFIX = 'pipelines.kubeflow.org/artifact-key-prefix'
BINDING = 'pipelines.kubeflow.org/artifact-root-binding'
ROOT_KEYS = (ROOT, BUCKET, PREFIX, BINDING)
REPOSITORIES = 'artifact-repositories'
DEFAULT_REPOSITORY = 'workflows.argoproj.io/default-artifact-repository'
SCHEMES = {'s3': 's3', 'gcs': 'gs'}


def reference(annotation):
    # Simple tags retain dotted annotation keys; expression maps split dots.
    return '{{workflow.annotations.' + annotation + '}}'


def parse_root(root):
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
    return location


def root_annotations(root):
    """Annotations for a compile-time root; without one, only the binding
    marker that lets a submitter bind the namespace repository later."""
    if root is None:
        # Argo validates every annotation reference when a template is
        # created, so the keys exist and the submitter fills them in.
        return {ROOT: '', BUCKET: '', PREFIX: '', BINDING: 'v1'}
    location = parse_root(root)
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
    annotations.update(values)


def repository_root(repository):
    """The ``scheme://bucket`` an Argo artifact repository entry serves."""
    if not isinstance(repository, dict):
        raise ValueError(
            'Argo artifact repository configuration must be an object.'
        )
    for driver, scheme in SCHEMES.items():
        config = repository.get(driver)
        if isinstance(config, dict) and config.get('bucket'):
            return f'{scheme}://{config["bucket"]}'
    if 'plugin' in repository:
        raise ValueError(
            'Pipelines need a native S3/GCS artifact repository; this namespace defaults to a repository plugin.'
        )
    raise ValueError('Argo artifact repository entry names no S3/GCS bucket.')


def bind_root(manifest, spec, repositories, default, requested=None):
    """Bind the run's artifact root to the namespace's Argo repositories.

    ``repositories`` maps entry keys to their configuration and ``default`` is
    the entry Argo uses without a reference. No requested root means the
    default entry's bucket. A requested root must be served by an entry; a
    non-default entry is selected with ``artifactRepositoryRef``. A package
    without root bindings (hand-written, A01) is left alone unless a root is
    requested. Returns the bound root, or None when nothing was bound.
    """
    annotations = manifest.setdefault('metadata', {}).setdefault(
        'annotations', {}
    )
    requested = requested or None
    if requested is None and annotations.get(BINDING) != 'v1':
        return None
    roots = {}
    for key, value in repositories.items():
        try:
            roots[key] = repository_root(value)
        except ValueError:
            # Entries that are not S3/GCS buckets cannot serve pipelines.
            continue
    if requested is None:
        if default not in roots:
            if default in repositories:
                repository_root(repositories[default])
            raise ValueError(
                'Configure an Argo artifact repository for this namespace '
                '(an artifact-repositories ConfigMap with a default entry) '
                'before running pipelines.'
            )
        override_root(manifest, roots[default])
        spec.pop('artifactRepositoryRef', None)
        return roots[default]
    location = parse_root(requested)
    bucket = f'{location.scheme}://{location.netloc}'
    key = next((key for key, root in roots.items() if root == bucket), None)
    if key is None:
        raise ValueError(
            f'No artifact repository in this namespace serves {bucket}; '
            f'available: {", ".join(sorted(set(roots.values()))) or "none"}. '
            'Add an entry to the artifact-repositories ConfigMap or choose a served bucket.'
        )
    override_root(manifest, requested)
    if key == default:
        spec.pop('artifactRepositoryRef', None)
    else:
        spec['artifactRepositoryRef'] = {'key': key}
    return requested.rstrip('/')
