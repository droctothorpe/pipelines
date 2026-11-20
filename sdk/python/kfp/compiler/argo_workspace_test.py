# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0

import pytest
import yaml

from kfp import compiler, dsl


@dsl.component
def echo_path(path: str) -> str:
    return path


def test_workspace_uses_native_claim_and_conditional_mounts(tmp_path):
    patch = {
        'accessModes': ['ReadWriteOnce'],
        'storageClassName': 'standard',
        'resources': {'requests': {'storage': '99Gi'}},
    }
    config = dsl.PipelineConfig(
        workspace=dsl.WorkspaceConfig(
            size='1Gi',
            kubernetes=dsl.KubernetesWorkspaceConfig(pvcSpecPatch=patch),
        )
    )

    @dsl.pipeline(pipeline_config=config)
    def pipeline():
        path = echo_path(path=dsl.WORKSPACE_PATH_PLACEHOLDER)
        echo_path(path=path.output)

    output = tmp_path / 'workspace.yaml'
    compiler.Compiler().compile(pipeline, str(output))
    spec = yaml.safe_load(output.read_text())['spec']
    claim = spec['volumeClaimTemplates'][0]
    assert claim['metadata']['name'] == 'kfp-workspace'
    assert claim['spec']['resources']['requests']['storage'] == '1Gi'
    assert patch['resources']['requests']['storage'] == '99Gi'
    assert '/kfp-workspace' in spec['podSpecPatch']
    assert 'inputs.parameters' in spec['podSpecPatch']
    assert '{{$.workspace_path}}' not in output.read_text()
    leaves = [t for t in spec['templates'] if 'container' in t]
    assert all('workflow.uid' in t['memoize']['key'] for t in leaves)
    assert all(
        next(
            p['default']
            for p in t['inputs']['parameters']
            if p['name'] == 'kfp-workspace-strings'
        )
        == '["path"]'
        for t in leaves
    )
    assert all(' ? ' in t['memoize']['key'] for t in leaves), (
        'Only workspace users get a run-scoped cache key'
    )


def test_workspace_without_access_mode_reports_missing_deployment_default(
    tmp_path,
):
    @dsl.pipeline(
        pipeline_config=dsl.PipelineConfig(
            workspace=dsl.WorkspaceConfig(size='1Gi')
        )
    )
    def pipeline():
        echo_path(path=dsl.WORKSPACE_PATH_PLACEHOLDER)

    with pytest.raises(ValueError, match='accessModes'):
        compiler.Compiler().compile(pipeline, str(tmp_path / 'missing.yaml'))
