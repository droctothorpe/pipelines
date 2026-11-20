// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import type { NativeResource } from './ArgoResources';
import { needsArtifactListStaging } from './NativeArtifactLists';

export const ARTIFACT_ROOT = 'pipelines.kubeflow.org/artifact-repository';
const BUCKET = 'pipelines.kubeflow.org/artifact-bucket';
const PREFIX = 'pipelines.kubeflow.org/artifact-key-prefix';
const BINDING = 'pipelines.kubeflow.org/artifact-root-binding';

export function workflowArtifactRoot(version: NativeResource, pipelineRoot?: string) {
  const annotations: Record<string, string> = Object.fromEntries(
    Object.entries(version.metadata.annotations || {}).filter(([key]) =>
      [ARTIFACT_ROOT, BUCKET, PREFIX, BINDING].includes(key),
    ),
  );
  let spec: Record<string, any> = { workflowTemplateRef: { name: version.metadata.name } };
  if (pipelineRoot) {
    const match = /^(s3|gs):\/\/([A-Za-z0-9][A-Za-z0-9._-]*)(\/[^?#]*)?$/.exec(pipelineRoot);
    if (!match)
      throw new Error(
        'Pipeline artifact roots must be s3://bucket[/prefix] or gs://bucket[/prefix].',
      );
    const root = pipelineRoot.replace(/\/+$/, '');
    if (root !== annotations[ARTIFACT_ROOT]?.replace(/\/+$/, '')) {
      if (annotations[BINDING] !== 'v1')
        throw new Error('Recompile this pipeline to enable pipeline-root overrides.');
      const previous = annotations[ARTIFACT_ROOT]?.startsWith('s3:') ? 's3' : 'gcs';
      const driver = match[1] === 's3' ? 's3' : 'gcs';
      if (previous !== driver) {
        // A version is immutable; switching artifact drivers needs an inline copy.
        spec = structuredClone(version.spec || {});
        delete spec.workflowMetadata;
        for (const template of spec.templates || []) {
          for (const artifact of template.outputs?.artifacts || []) {
            const location = artifact[previous];
            if (location?.bucket !== `{{workflow.annotations.${BUCKET}}}`) continue;
            if (Object.keys(location).some((key) => !['bucket', 'key'].includes(key))) {
              throw new Error(
                'Recompile for the new storage scheme: artifact driver has explicit settings.',
              );
            }
            artifact[driver] = location;
            delete artifact[previous];
          }
        }
      }
      const prefix = (match[3] || '').replace(/^\/+|\/+$/g, '');
      Object.assign(annotations, {
        [ARTIFACT_ROOT]: root,
        [BUCKET]: match[2],
        [PREFIX]: prefix ? prefix + '/' : '',
      });
    }
  }
  if (needsArtifactListStaging(version.spec) && spec.workflowTemplateRef) {
    spec = structuredClone(version.spec || {});
    delete spec.workflowMetadata;
  }
  if (annotations[ARTIFACT_ROOT])
    annotations['pipelines.kubeflow.org/pipeline-root'] = annotations[ARTIFACT_ROOT];
  return { annotations, spec };
}
