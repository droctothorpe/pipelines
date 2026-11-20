// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import { useQuery } from '@tanstack/react-query';
import { Button } from '@mui/material';
import Banner from 'src/components/Banner';
import {
  argoArtifactUrl,
  argoRequest,
  type ArgoWorkflow,
  type ArgoNode,
  type ArgoMetadata,
} from 'src/lib/Argo';
import {
  getArtifactPreviewDescriptor,
  MAX_PREVIEW_BYTES,
  parseArtifactContentPreview,
} from 'src/lib/v2/ArtifactContentPreview';
import { DatasetPreviewTable, ModelPreviewSummary } from './ArtifactContentPreview';

export function NativeArtifactPreview({
  run,
  node,
  artifact,
}: {
  run: ArgoWorkflow;
  node: ArgoNode;
  artifact: ArgoMetadata['artifacts'][number];
}) {
  const query = useQuery({
    queryKey: [
      'native',
      run.metadata.namespace,
      run.metadata.uid,
      node.id,
      artifact.port,
      'content-preview',
      JSON.stringify(artifact.metadata._kfp_preview),
    ],
    retry: false,
    queryFn: async ({ signal }) => {
      const descriptor = getArtifactPreviewDescriptor(artifact.metadata);
      if (!descriptor) return null;
      const url =
        descriptor.version === 2
          ? argoArtifactUrl(run, node, artifact.port + '-preview')
          : argoArtifactUrl(run, node, artifact.port) + '/_kfp_preview.json';
      const response = await argoRequest(url, signal);
      const reader = response.body?.getReader();
      if (!reader) throw new Error('Artifact preview response was empty.');
      let size = 0,
        content = '';
      const decoder = new TextDecoder();
      try {
        while (true) {
          const result = await reader.read();
          if (result.done) break;
          size += result.value.byteLength;
          if (size > MAX_PREVIEW_BYTES)
            throw new Error('Artifact preview exceeds the 64 KiB limit.');
          content += decoder.decode(result.value, { stream: true });
        }
        content += decoder.decode();
      } finally {
        await reader.cancel();
      }
      return parseArtifactContentPreview(
        content,
        artifact.type.startsWith('system.Dataset@') ? 'dataset' : 'model',
      );
    },
  });
  if (query.isPending) return <Banner mode='info' message='Artifact preview is loading.' />;
  if (query.error)
    return (
      <>
        <Banner
          mode='error'
          message='Unable to display the artifact preview.'
          additionalInfo={query.error.message}
        />
        <Button size='small' onClick={() => void query.refetch()}>
          Retry preview
        </Button>
      </>
    );
  if (!query.data)
    return (
      <Banner
        mode='info'
        message='No preview is available for this artifact. Check the pipeline and component preview settings, supported formats, component SDK, and logs.'
      />
    );
  return query.data.kind === 'dataset' ? (
    <DatasetPreviewTable preview={query.data} />
  ) : (
    <ModelPreviewSummary preview={query.data} />
  );
}
