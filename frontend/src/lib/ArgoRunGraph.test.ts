// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from 'vitest';
import { argoRunView } from './ArgoRunGraph';
import type { ArgoWorkflow } from './Argo';
import { getTaskNodeKey, getArtifactNodeKey, NodeTypeNames } from './v2/StaticFlow';
import { PipelineTaskTaskState } from 'src/components/graph/Constants';

describe('native executions in the stock graph', () => {
  it('hides the engine root, renders typed output ports and connects artifact consumers', () => {
    const run: ArgoWorkflow = {
      metadata: { name: 'wf', uid: 'uid', namespace: 'team' },
      spec: {},
      status: {
        nodes: {
          wf: { id: 'wf', displayName: 'wf', type: 'DAG', children: ['prepare'] },
          prepare: {
            id: 'prepare',
            displayName: 'prepare',
            type: 'Pod',
            boundaryID: 'wf',
            phase: 'Succeeded',
            memoizationStatus: { hit: true },
            children: ['train'],
            outputs: {
              artifacts: [
                { name: 'dataset', s3: { bucket: 'data', key: 'producer/dataset' } },
                { name: 'kfp-metadata' },
                { name: 'dataset-metadata' },
                { name: 'main-logs' },
              ],
            },
          },
          train: {
            id: 'train',
            displayName: 'train',
            type: 'Pod',
            boundaryID: 'wf',
            phase: 'Running',
            inputs: {
              artifacts: [{ name: 'dataset', s3: { bucket: 'data', key: 'producer/dataset' } }],
            },
          },
        },
      },
    };
    const graph = argoRunView(run);
    expect(
      graph.elements
        .filter((element) => 'data' in element)
        .map((element) => element.id)
        .sort(),
    ).toEqual(
      [
        getTaskNodeKey('prepare'),
        getTaskNodeKey('train'),
        getArtifactNodeKey('prepare', 'dataset'),
      ].sort(),
    );
    expect(
      graph.elements.find((element) => element.id === getTaskNodeKey('prepare'))?.data?.state,
    ).toBe(PipelineTaskTaskState.CACHED);
    expect(graph.elements).toContainEqual(
      expect.objectContaining({
        source: getArtifactNodeKey('prepare', 'dataset'),
        target: getTaskNodeKey('train'),
      }),
    );
    expect(graph.describe(getArtifactNodeKey('prepare', 'dataset'))).toMatchObject({
      node: { id: 'prepare' },
      artifact: 'dataset',
    });
  });
  it('expands actual loop iterations without flattening their tasks into the parent graph', () => {
    const run: ArgoWorkflow = {
      metadata: { name: 'wf', uid: 'uid', namespace: 'team' },
      spec: {},
      status: {
        nodes: {
          wf: { id: 'wf', displayName: 'wf', type: 'DAG', children: ['loop'] },
          loop: {
            id: 'loop',
            displayName: 'for-loop',
            type: 'DAG',
            boundaryID: 'wf',
            children: ['iterations'],
            outboundNodes: ['task0', 'task1'],
          },
          iterations: {
            id: 'iterations',
            displayName: 'iteration',
            type: 'TaskGroup',
            boundaryID: 'loop',
            children: ['iteration0', 'iteration1'],
          },
          iteration0: {
            id: 'iteration0',
            displayName: 'iteration(0:1)',
            type: 'DAG',
            boundaryID: 'loop',
            children: ['task0'],
            outboundNodes: ['task0'],
          },
          iteration1: {
            id: 'iteration1',
            displayName: 'iteration(1:2)',
            type: 'DAG',
            boundaryID: 'loop',
            children: ['task1'],
            outboundNodes: ['task1'],
          },
          task0: {
            id: 'task0',
            displayName: 'number',
            type: 'Pod',
            boundaryID: 'iteration0',
            children: ['total'],
          },
          task1: {
            id: 'task1',
            displayName: 'number',
            type: 'Pod',
            boundaryID: 'iteration1',
            children: ['total'],
          },
          total: { id: 'total', displayName: 'total', type: 'Pod', boundaryID: 'wf' },
        },
      },
    };
    const graph = argoRunView(run);
    expect(graph.elements.find((element) => element.id === getTaskNodeKey('loop'))?.type).toBe(
      NodeTypeNames.SUB_DAG,
    );
    expect(graph.elements).toContainEqual(
      expect.objectContaining({ source: getTaskNodeKey('loop'), target: getTaskNodeKey('total') }),
    );
    expect(
      graph
        .resolve(['root', 'loop'])
        .filter((element) => 'data' in element)
        .map((element) => element.id),
    ).toEqual([getTaskNodeKey('iterations')]);
    expect(
      graph
        .resolve(['root', 'loop', 'iterations'])
        .filter((element) => 'data' in element)
        .map((element) => element.id)
        .sort(),
    ).toEqual([getTaskNodeKey('iteration0'), getTaskNodeKey('iteration1')]);
    expect(graph.findTask('task0')).toMatchObject({
      layers: ['root', 'loop', 'iterations', 'iteration0'],
      element: { id: getTaskNodeKey('task0') },
    });
    expect(
      graph
        .resolve(['root', 'loop', 'iterations', 'iteration0'])
        .filter((element) => 'data' in element)
        .map((element) => element.id),
    ).toEqual([getTaskNodeKey('task0')]);
  });
});
