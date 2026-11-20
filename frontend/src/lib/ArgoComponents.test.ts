// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import { afterEach, expect, it, vi } from 'vitest';
import type { ArgoWorkflow } from './Argo';
import { argoRunView } from './ArgoRunGraph';
import { argoStaticView } from './ArgoGraph';
import { taskLogs } from './NativeUi';
import { displayParameters } from './ArgoComponents';
import { getTaskNodeKey, NodeTypeNames } from './v2/StaticFlow';

const templates = [
  { name: 'root', dag: { tasks: [{ name: 'produce', template: 'wrapper' }] } },
  {
    name: 'wrapper',
    metadata: { annotations: { 'pipelines.kubeflow.org/component-wrapper': 'true' } },
    dag: {
      tasks: [
        { name: 'execute', template: 'body' },
        { name: 'validate', template: 'validation' },
      ],
    },
  },
  { name: 'body', container: { image: 'test' } },
  { name: 'validation', suspend: { duration: '0' } },
];
const run: ArgoWorkflow = {
  metadata: { name: 'wf', uid: 'uid', namespace: 'team' },
  spec: { templates, entrypoint: 'root' },
  status: {
    nodes: {
      wf: { id: 'wf', displayName: 'wf', type: 'DAG', children: ['produce'] },
      produce: {
        id: 'produce',
        name: 'wf.produce',
        displayName: 'produce',
        templateName: 'wrapper',
        type: 'DAG',
        phase: 'Error',
        boundaryID: 'wf',
        children: ['execute'],
        outboundNodes: ['validate'],
      },
      execute: {
        id: 'execute',
        name: 'wf.produce.execute',
        displayName: 'execute',
        type: 'Pod',
        boundaryID: 'produce',
        phase: 'Succeeded',
        children: ['validate'],
        outputs: { artifacts: [{ name: 'main-logs', s3: { bucket: 'data', key: 'logs' } }] },
      },
      validate: {
        id: 'validate',
        name: 'wf.produce.validate',
        displayName: 'validate',
        type: 'Skipped',
        phase: 'Error',
        message: 'invalid integer output',
        boundaryID: 'produce',
        children: ['consumer'],
      },
      consumer: {
        id: 'consumer',
        displayName: 'consumer',
        type: 'Pod',
        boundaryID: 'wf',
        phase: 'Omitted',
      },
    },
  },
};
afterEach(() => vi.unstubAllGlobals());
it('shows nullable values without leaking their encoded wire representation', () => {
  const resource: ArgoWorkflow = {
    metadata: { name: 'wf', uid: 'uid', namespace: 'team' },
    spec: {
      templates: [
        {
          name: 'component',
          metadata: {
            annotations: {
              'pipelines.kubeflow.org/input-parameter-types': JSON.stringify({
                missing: 'NullableString',
                literal: 'NullableString',
                empty: 'NullableString',
              }),
            },
          },
        },
      ],
    },
  };
  const node = {
    id: 'task',
    displayName: 'task',
    type: 'Pod',
    templateName: 'component',
    inputs: {
      parameters: [
        { name: 'missing', value: 'null' },
        { name: 'literal', value: '"null"' },
        { name: 'empty', value: '""' },
        { name: 'kfp-workspace-strings', value: '[]' },
      ],
    },
  };
  expect(displayParameters(resource, node, 'inputs')).toEqual([
    ['missing', 'None'],
    ['literal', 'null'],
    ['empty', ''],
  ]);
});
it('presents a native importer as one importer task, not a control subgraph', () => {
  const imported: ArgoWorkflow = {
    metadata: { name: 'wf', uid: 'uid', namespace: 'team' },
    spec: {
      templates: [
        {
          name: 'importer-template',
          metadata: { annotations: { 'pipelines.kubeflow.org/component-type': 'IMPORTER' } },
        },
      ],
    },
    status: {
      nodes: {
        wf: { id: 'wf', displayName: 'wf', type: 'DAG' },
        importer: {
          id: 'importer',
          displayName: 'importer',
          templateName: 'importer-template',
          type: 'DAG',
          boundaryID: 'wf',
        },
        resolve: { id: 'resolve', displayName: 'resolve', type: 'Suspend', boundaryID: 'importer' },
      },
    },
  };
  const graph = argoRunView(imported);
  expect(graph.nodes.map((node) => node.id)).toEqual(['wf', 'importer']);
  expect(graph.describe(getTaskNodeKey('importer')).node?.type).toBe('Importer');
  expect(graph.elements.find((e) => e.id === getTaskNodeKey('importer'))?.type).toBe(
    NodeTypeNames.EXECUTION,
  );
});
it('shows a component rather than its execution/validation machinery in live and static graphs', () => {
  const graph = argoRunView(run);
  expect(graph.elements.find((e) => e.id === getTaskNodeKey('produce'))).toMatchObject({
    type: NodeTypeNames.EXECUTION,
    data: { lifecycleMessage: 'invalid integer output' },
  });
  expect(graph.elements).toContainEqual(
    expect.objectContaining({
      source: getTaskNodeKey('produce'),
      target: getTaskNodeKey('consumer'),
    }),
  );
  expect(graph.describe(getTaskNodeKey('produce')).node?.message).toBe('invalid integer output');
  expect(graph.nodes.map((node) => node.id)).toEqual(['wf', 'produce', 'consumer']);
  const source = argoStaticView({ kind: 'Workflow', spec: { entrypoint: 'root', templates } });
  expect(source.elements.find((e) => e.id === getTaskNodeKey('produce'))?.type).toBe(
    NodeTypeNames.EXECUTION,
  );
  expect(source.describe(['root'], getTaskNodeKey('produce')).template?.container?.image).toBe(
    'test',
  );
});
it('resolves component logs to its actual pod without changing the user-facing node identity', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(
      async (path: string) =>
        new Response(
          path.endsWith('/main-logs') ? 'container logs' : JSON.stringify({ items: [] }),
        ),
    ),
  );
  expect(await taskLogs(run, run.status!.nodes!.produce)).toEqual(['container logs']);
  expect(vi.mocked(fetch).mock.calls[0][0]).toContain('/execute/main-logs');
});
