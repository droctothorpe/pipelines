// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import { useQuery } from '@tanstack/react-query';
import {
  getArgoMetadata,
  getArgoWorkflow,
  hasArgoMetadata,
  type ArgoWorkflow,
  type ArgoNode,
  type ArgoMetadata,
} from './Argo';
import { listResources } from './ArgoResources';
import { listUiRuns, listVersions } from './NativeUi';
import { useNativeUi } from './NativeUiContext';
export function useInventory() {
  const { namespace } = useNativeUi();
  const pipelines = useQuery({
    refetchOnMount: 'always',
    queryKey: ['native', namespace, 'pipelines'],
    queryFn: ({ signal }) => listResources(namespace, 'pipelines', signal),
    staleTime: 5000,
  });
  const versions = useQuery({
    refetchOnMount: 'always',
    queryKey: ['native', namespace, 'versions'],
    queryFn: ({ signal }) => listVersions(namespace, signal),
    staleTime: 5000,
  });
  const experiments = useQuery({
    refetchOnMount: 'always',
    queryKey: ['native', namespace, 'experiments'],
    queryFn: ({ signal }) => listResources(namespace, 'experiments', signal),
    staleTime: 5000,
  });
  const runs = useQuery({
    queryKey: ['native', namespace, 'runs'],
    queryFn: ({ signal }) => listUiRuns(namespace, signal),
    refetchInterval: 5000,
  });
  const schedules = useQuery({
    refetchOnMount: 'always',
    queryKey: ['native', namespace, 'schedules'],
    queryFn: ({ signal }) => listResources(namespace, 'cron-workflows', signal),
    staleTime: 5000,
  });
  return {
    pipelines,
    versions,
    experiments,
    runs,
    schedules,
    error: pipelines.error || versions.error || experiments.error || runs.error || schedules.error,
    pending:
      pipelines.isPending ||
      versions.isPending ||
      experiments.isPending ||
      runs.isPending ||
      schedules.isPending,
  };
}
export interface NativeArtifact {
  id: string;
  run: ArgoWorkflow;
  node: ArgoNode;
  artifact: ArgoMetadata['artifacts'][number];
}
export function useArtifactInventory(enabled = true) {
  const { namespace } = useNativeUi();
  return useQuery({
    queryKey: ['native', namespace, 'artifacts'],
    enabled,
    staleTime: 30000,
    queryFn: async ({ signal }) => {
      const runs = (await listUiRuns(namespace, signal)).sort((a, b) =>
        (b.metadata.creationTimestamp || '').localeCompare(a.metadata.creationTimestamp || ''),
      );
      const collected = await Promise.all(
        runs.slice(0, 50).map(async (entry) => {
          const run = await getArgoWorkflow(entry, signal);
          const nodes = Object.values(run.status?.nodes || {}).filter(hasArgoMetadata);
          return (
            await Promise.all(
              nodes.map(async (node) => {
                const metadata = await getArgoMetadata(run, node, signal);
                return metadata.artifacts.map((artifact) => ({
                  id: `${run.metadata.uid}/${node.id}/${artifact.port}`,
                  run,
                  node,
                  artifact,
                }));
              }),
            )
          ).flat();
        }),
      );
      // Cache hits point to the original producer, not a second artifact.
      const unique = new Map<string, NativeArtifact>();
      for (const entry of collected.flat()) {
        const key = `${entry.artifact.producer.run}/${entry.artifact.producer.task}/${entry.artifact.port}/${entry.artifact.uri}`;
        if (!unique.has(key)) unique.set(key, entry);
      }
      return { items: [...unique.values()], truncated: runs.length > 50 };
    },
  });
}
