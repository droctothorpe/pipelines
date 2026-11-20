# Copyright 2021-2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Compile captured KFP DSL graphs to ordinary Argo resources."""

from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from kfp.dsl import base_component
from kfp.dsl.types.type_utils import TypeCheckManager


class _ArgoDumper(yaml.SafeDumper):
    """Also quote YAML 1.1 booleans omitted by PyYAML's implicit resolver."""


def _string(dumper, value):
    node = dumper.represent_str(value)
    if value.lower() in ('y', 'n'):
        node.style = "'"
    return node


_ArgoDumper.add_representer(str, _string)


class Compiler:
    """Compile KFP Python source to native Argo YAML.

    WorkflowTemplate is the default reusable output. Pipeline versions
    are content-addressed; callers must enforce immutability when
    applying them. Image digests identify locally built images for cache
    correctness without requiring registry access during offline
    compilation.
    """

    def __init__(
        self,
        artifact_repository: str = 's3://argo-artifacts',
        service_account_name: str = 'argo-workflow',
        cache_config_map: str = 'kfp-cache',
        image_digests: Optional[Dict[str, str]] = None,
        disable_caching: bool = False,
    ):
        self.artifact_repository = artifact_repository
        self.service_account_name = service_account_name
        self.cache_config_map = cache_config_map
        self.image_digests = image_digests or {}
        self.disable_caching = disable_caching

    def compile(
        self,
        pipeline_func: base_component.BaseComponent,
        package_path: str,
        pipeline_name: Optional[str] = None,
        pipeline_display_name: Optional[str] = None,
        pipeline_parameters: Optional[Dict[str, Any]] = None,
        type_check: bool = True,
        kubernetes_manifest_options=None,
        kubernetes_manifest_format: bool = False,
        *,
        resource_kind: str = 'WorkflowTemplate',
        schedule: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> None:
        """Write a WorkflowTemplate, Workflow, or suspended CronWorkflow.

        Unsupported DSL or task settings fail with actionable errors;
        there is no KFP IR or local-execution fallback. Argo owns
        artifact transfer and status. CronWorkflow output requires an
        explicit cron schedule.
        """
        from kfp.compiler.argo_compiler import compile_argo

        if not isinstance(pipeline_func, base_component.BaseComponent):
            raise ValueError(
                'Expected a component or pipeline created with @dsl.component or @dsl.pipeline.'
            )
        if (
            kubernetes_manifest_options is not None
            or kubernetes_manifest_format
        ):
            raise ValueError(
                'KFP PipelineVersion manifests are no longer emitted; use resource_kind="WorkflowTemplate".'
            )
        with TypeCheckManager(enable=type_check):
            manifest = compile_argo(
                pipeline_func,
                self,
                pipeline_name,
                pipeline_display_name,
                pipeline_parameters or {},
                resource_kind,
                schedule,
            )
        if namespace:
            manifest['metadata']['namespace'] = namespace
        target = Path(package_path).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            yaml.dump(manifest, Dumper=_ArgoDumper, sort_keys=False)
        )
