# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Resolve Argo's namespace repository configuration without reading Secrets."""

import yaml

from kfp.compiler.argo_artifact_lists import bind_repository, needs_binding
from kfp.server_api.exceptions import ApiException


def prepare_staging(spec, get_config_map):
    if not needs_binding(spec):
        return
    reference = spec.get('artifactRepositoryRef')
    name = (reference or {}).get('configMap') or 'artifact-repositories'
    try:
        config = get_config_map(name)
    except ApiException as error:
        if reference is not None or error.status != 404:
            raise
        config = {}
    key = (reference or {}).get('key') or config.get('metadata', {}).get(
        'annotations', {}
    ).get('workflows.argoproj.io/default-artifact-repository')
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
