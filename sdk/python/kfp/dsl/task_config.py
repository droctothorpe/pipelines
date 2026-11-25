# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Portable component context annotation; not a driver integration."""

import dataclasses
from typing import Any, Dict, List, Optional


@dataclasses.dataclass
class TaskConfig:
    """Configuration annotation retained for typed component definitions.

    The native compiler supplies selected passthrough fields from the task's
    Kubernetes configuration. ``apply_to_task`` controls whether each selected
    field also applies to the component pod; no driver pod populates this value.
    Python components also receive conditional workspace volumes and resolved
    structured settings, including resource claims. Mixed dynamic declarations
    and raw-container structured TaskConfig still require additional lowering.
    """

    affinity: Optional[Dict[str, Any]] = None
    tolerations: Optional[List[Dict[str, Any]]] = None
    node_selector: Optional[Dict[str, str]] = None
    env: Optional[List[Dict[str, Any]]] = None
    volumes: Optional[List[Dict[str, Any]]] = None
    volume_mounts: Optional[List[Dict[str, Any]]] = None
    resources: Optional[Dict[str, Any]] = None
    resource_claims: Optional[List[Dict[str, Any]]] = None
