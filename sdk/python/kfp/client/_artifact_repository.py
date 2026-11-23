# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Resolve Argo's namespace repository configuration without reading
Secrets."""

import yaml

from kfp.compiler.argo_artifact_lists import bind_repository, needs_binding
from kfp.compiler.argo_artifacts import (
    DEFAULT_REPOSITORY,
    REPOSITORIES,
    bind_root,
)
from kfp.server_api.exceptions import ApiException


def _entries(config):
    entries = {}
    for key, text in (config.get('data') or {}).items():
        if not text:
            continue
        parsed = yaml.safe_load(text)
        if not isinstance(parsed, dict):
            raise ValueError(
                'Argo artifact repository configuration must be an object.'
            )
        entries[key] = parsed
    return entries


def namespace_repositories(get_config_map):
    """Argo's chain for a namespace: the ``artifact-repositories`` ConfigMap's
    entries and its annotated default, else the controller's default repository
    (readable only where the controller lives)."""
    try:
        config = get_config_map(REPOSITORIES)
    except ApiException as error:
        if error.status != 404:
            raise
        config = {}
    entries = _entries(config)
    default = (
        (config.get('metadata') or {})
        .get('annotations', {})
        .get(DEFAULT_REPOSITORY)
    )
    if entries and default:
        return entries, default
    try:
        controller = get_config_map('workflow-controller-configmap')
    except ApiException as error:
        if error.status not in (403, 404):
            raise
        controller = {}
    text = (controller.get('data') or {}).get('artifactRepository')
    if text:
        parsed = yaml.safe_load(text)
        if isinstance(parsed, dict):
            entries['default'] = parsed
            default = 'default'
    return entries, default


def bind_namespace_root(manifest, spec, get_config_map, requested=None):
    """Bind a run's artifact root the way Argo would place its artifacts."""
    entries, default = namespace_repositories(get_config_map)
    try:
        return bind_root(manifest, spec, entries, default, requested)
    except ValueError as error:
        raise ApiException(status=400, reason=str(error)) from error


def prepare_staging(spec, get_config_map):
    if not needs_binding(spec):
        return
    reference = spec.get('artifactRepositoryRef')
    name = (reference or {}).get('configMap') or REPOSITORIES
    try:
        config = get_config_map(name)
    except ApiException as error:
        if reference is not None or error.status != 404:
            raise
        config = {}
    key = (reference or {}).get('key') or config.get('metadata', {}).get(
        'annotations', {}
    ).get(DEFAULT_REPOSITORY)
    if key:
        text = config.get('data', {}).get(key)
    elif reference is not None:
        raise ValueError(
            'Artifact repository reference needs a key or a namespace default annotation.'
        )
    else:
        config = get_config_map('workflow-controller-configmap')
        text = config.get('data', {}).get('artifactRepository')
    if not text:
        raise ValueError(
            'Configure an Argo artifact repository before submitting artifact-list consumers.'
        )
    repository = yaml.safe_load(text)
    if not isinstance(repository, dict):
        raise ValueError(
            'Argo artifact repository configuration must be an object.'
        )
    if 'plugin' in repository:
        raise ValueError(
            'Artifact-list staging does not yet support repository plugins; use a native S3/GCS repository.'
        )
    bind_repository(spec, repository)
