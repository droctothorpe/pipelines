// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import type { ArgoNode, ArgoWorkflow } from './Argo';

type Template = { name?: string; metadata?: { annotations?: Record<string, string> } };
export const isComponentTemplate = (template?: Template) =>
  template?.metadata?.annotations?.['pipelines.kubeflow.org/component-wrapper'] === 'true' ||
  template?.metadata?.annotations?.['pipelines.kubeflow.org/component-type'] === 'IMPORTER';

function components(run: ArgoWorkflow) {
  const templates = run.spec.templates || run.status?.storedWorkflowTemplateSpec?.templates;
  const names = new Map(
    (Array.isArray(templates) ? (templates as Template[]) : [])
      .filter(isComponentTemplate)
      .map((t) => [
        t.name,
        t.metadata?.annotations?.['pipelines.kubeflow.org/component-type'] === 'IMPORTER'
          ? 'Importer'
          : 'Container',
      ]),
  );
  const nodes = Object.values(run.status?.nodes || {});
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const wrappers = new Set(
    nodes
      .filter((node) => node.type !== 'Retry' && names.has(node.templateName))
      .map((node) => node.id),
  );
  const owners = new Map<string, string>();
  for (const node of nodes) {
    let id = node.boundaryID;
    const seen = new Set<string>();
    while (id && !seen.has(id)) {
      seen.add(id);
      if (wrappers.has(id)) {
        owners.set(node.id, id);
        break;
      }
      id = byId.get(id)?.boundaryID;
    }
  }
  return { nodes, wrappers, owners, names };
}

/** Present one user component while retaining its real status, outputs and identity. */
export function componentNodeViews(run: ArgoWorkflow) {
  const { nodes, wrappers, owners, names } = components(run);
  const failures = new Map<string, string>();
  for (const node of nodes) {
    const owner = owners.get(node.id);
    if (owner && ['Failed', 'Error'].includes(node.phase || '') && node.message)
      failures.set(owner, node.message);
  }
  return nodes
    .filter((node) => !owners.has(node.id))
    .map((node) =>
      wrappers.has(node.id)
        ? {
            ...node,
            type: names.get(node.templateName) || 'Container',
            message: node.message || failures.get(node.id),
          }
        : node,
    );
}

export function displayParameters(
  run: ArgoWorkflow,
  node: ArgoNode,
  direction: 'inputs' | 'outputs',
): Array<[string, string]> {
  const templates = run.spec.templates || run.status?.storedWorkflowTemplateSpec?.templates;
  const template = (Array.isArray(templates) ? (templates as Template[]) : []).find(
    (t) => t.name === node.templateName,
  );
  let kinds: Record<string, string> = {};
  try {
    kinds = JSON.parse(
      template?.metadata?.annotations?.[
        `pipelines.kubeflow.org/${direction === 'inputs' ? 'input' : 'output'}-parameter-types`
      ] || '{}',
    );
  } catch {
    /* Older native manifests may not have type annotations. */
  }
  const parameters = node[direction]?.parameters || [];
  const values = new Map(parameters.map((p) => [p.name, p.value]));
  return parameters
    .filter(
      (p) =>
        !/^(kfp-meta-|kfp-uri-|kfp-present-|kfp-workspace-|kfp-config-|kfp-metadata$)/.test(
          p.name,
        ) && values.get('kfp-present-' + p.name) !== 'false',
    )
    .map((p) => {
      let value = p.value || '';
      if (kinds[p.name]?.startsWith('Nullable')) {
        try {
          const decoded = JSON.parse(value);
          value =
            decoded === null
              ? 'None'
              : typeof decoded === 'string'
                ? decoded
                : JSON.stringify(decoded);
        } catch {
          /* Preserve invalid output evidence. */
        }
      }
      return [p.name, value];
    });
}

export function componentPod(run: ArgoWorkflow, node: ArgoNode) {
  const { nodes, wrappers, owners } = components(run);
  if (!wrappers.has(node.id)) return node;
  return nodes.find((child) => owners.get(child.id) === node.id && child.type === 'Pod') || node;
}
