// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import { type ArgoWorkflow, type ArgoNode } from './Argo';
import { PipelineTaskTaskState } from 'src/components/graph/Constants';
import type { PipelineFlowElement } from './v2/FlowTypes';
import {
  buildGraphLayout,
  getTaskNodeKey,
  getTaskKeyFromNodeKey,
  getArtifactNodeKey,
  getKeysFromArtifactNodeKey,
  isArtifactNode,
  NodeTypeNames,
  TaskType,
} from './v2/StaticFlow';

/** Group actual Argo executions, including individual loop/retry attempts, for KFP's DAG widget. */
export function argoRunView(run: ArgoWorkflow) {
  const nodes = Object.values(run.status?.nodes || {});
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const root = nodes.find(
    (node) => node.name === run.metadata.name || node.id === run.metadata.name,
  );
  const isGroup = (node: ArgoNode) =>
    ['DAG', 'Steps', 'StepGroup', 'TaskGroup', 'Retry'].includes(node.type);
  const parents = new Map(nodes.map((node) => [node.id, node.boundaryID || root?.id]));
  for (const node of nodes)
    if (['TaskGroup', 'Retry', 'StepGroup'].includes(node.type))
      for (const child of node.children || []) if (byId.has(child)) parents.set(child, node.id);
  const phases: Record<string, PipelineTaskTaskState> = {
    Running: PipelineTaskTaskState.RUNNING,
    Succeeded: PipelineTaskTaskState.SUCCEEDED,
    Failed: PipelineTaskTaskState.FAILED,
    Error: PipelineTaskTaskState.FAILED,
    Skipped: PipelineTaskTaskState.SKIPPED,
    Omitted: PipelineTaskTaskState.SKIPPED,
  };
  function resolve(layers: string[]): PipelineFlowElement[] {
    const group = layers.length === 1 ? root?.id : layers[layers.length - 1];
    const visible =
      root && !isGroup(root) && layers.length === 1
        ? [root]
        : nodes.filter((node) => node.id !== root?.id && parents.get(node.id) === group);
    const ids = new Set(visible.map((node) => node.id));
    const elements: PipelineFlowElement[] = [];
    const edges = new Set<string>();
    const artifacts = new Map<string, string>();
    const edge = (source: string, target: string) => {
      const id = `${source}->${target}`;
      if (source !== target && !edges.has(id)) {
        edges.add(id);
        elements.push({ id, source, target });
      }
    };
    const visibleAncestor = (id: string) => {
      const seen = new Set<string>();
      while (!ids.has(id) && !seen.has(id)) {
        seen.add(id);
        const parent = parents.get(id);
        if (!parent || parent === id) return undefined;
        id = parent;
      }
      return ids.has(id) ? id : undefined;
    };
    for (const node of visible) {
      const task = getTaskNodeKey(node.id);
      elements.push({
        id: task,
        type: isGroup(node) ? NodeTypeNames.SUB_DAG : NodeTypeNames.EXECUTION,
        position: { x: 0, y: 0 },
        data: {
          label: node.displayName,
          taskId: node.id,
          taskType: isGroup(node) ? TaskType.DAG : TaskType.EXECUTOR,
          groupKind:
            node.type === 'TaskGroup' ? 'Loop' : node.type === 'Retry' ? 'Retry' : 'Sub-DAG',
          state: node.memoizationStatus?.hit
            ? PipelineTaskTaskState.CACHED
            : phases[node.phase || ''] || PipelineTaskTaskState.RUNTIME_STATE_UNSPECIFIED,
          lifecycleMessage: node.message,
        },
      });
      for (const artifact of node.outputs?.artifacts || []) {
        if (
          artifact.name === 'main-logs' ||
          artifact.name === 'kfp-metadata' ||
          artifact.name.endsWith('-metadata')
        )
          continue;
        const id = getArtifactNodeKey(node.id, artifact.name);
        elements.push({
          id,
          type: NodeTypeNames.ARTIFACT,
          position: { x: 0, y: 0 },
          data: { label: artifact.name, outputArtifactKey: artifact.name },
        });
        edge(task, id);
        if (artifact.s3?.key) artifacts.set(`${artifact.s3.bucket}/${artifact.s3.key}`, id);
      }
    }
    for (const node of visible) {
      for (const child of [
        ...(node.children || []),
        ...(node.outboundNodes || []).flatMap((id) => byId.get(id)?.children || []),
      ]) {
        const target = visibleAncestor(child);
        if (target) edge(getTaskNodeKey(node.id), getTaskNodeKey(target));
      }
      for (const input of node.inputs?.artifacts || []) {
        const source = artifacts.get(`${input.s3?.bucket}/${input.s3?.key}`);
        if (source) edge(source, getTaskNodeKey(node.id));
      }
    }
    return buildGraphLayout(elements);
  }
  return {
    elements: resolve(['root']),
    resolve,
    describe(id: string) {
      const [nodeId, artifact] = isArtifactNode(id)
        ? getKeysFromArtifactNodeKey(id)
        : [getTaskKeyFromNodeKey(id), undefined];
      return { node: byId.get(nodeId), artifact };
    },
  };
}
