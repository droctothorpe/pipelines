// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import type { NativeResource } from './ArgoResources';
import { namespaceRepositories, needsArtifactListStaging } from './NativeArtifactLists';

export const ARTIFACT_ROOT = 'pipelines.kubeflow.org/artifact-repository';
const BUCKET = 'pipelines.kubeflow.org/artifact-bucket';
const PREFIX = 'pipelines.kubeflow.org/artifact-key-prefix';
const BINDING = 'pipelines.kubeflow.org/artifact-root-binding';
const SCHEMES: Record<string, string> = { s3: 's3', gcs: 'gs' };

function parseRoot(root: string) {
  const match = /^(s3|gs):\/\/([A-Za-z0-9][A-Za-z0-9._-]*)(\/[^?#]*)?$/.exec(root);
  if (!match)
    throw new Error(
      'Pipeline artifact roots must be s3://bucket[/prefix] or gs://bucket[/prefix].',
    );
  const prefix = (match[3] || '').replace(/^\/+|\/+$/g, '');
  return { bucket: `${match[1]}://${match[2]}`, prefix: prefix ? prefix + '/' : '' };
}

/** The `scheme://bucket` an Argo artifact repository entry serves. */
export function repositoryRoot(repository: Record<string, any>): string {
  for (const [driver, scheme] of Object.entries(SCHEMES)) {
    const bucket = repository?.[driver]?.bucket;
    if (bucket) return `${scheme}://${bucket}`;
  }
  if (repository && 'plugin' in repository)
    throw new Error(
      'Pipelines need a native S3/GCS artifact repository; this namespace defaults to a repository plugin.',
    );
  throw new Error('Argo artifact repository entry names no S3/GCS bucket.');
}

/**
 * Compiled artifacts carry keys only; Argo places them in the repository it
 * resolves for the namespace. Bind the run to that repository's bucket, or to
 * the entry serving an explicit root, so the URIs the run records are the
 * places Argo writes. This is the stock namespace storage policy, taken from
 * Argo's `artifact-repositories` ConfigMap instead of `kfp-launcher`.
 */
export async function bindArtifactRoot(
  namespace: string,
  version: NativeResource,
  pipelineRoot?: string,
) {
  const annotations: Record<string, string> = Object.fromEntries(
    Object.entries(version.metadata.annotations || {}).filter(([key]) =>
      [ARTIFACT_ROOT, BUCKET, PREFIX, BINDING].includes(key),
    ),
  );
  let spec: Record<string, any> = { workflowTemplateRef: { name: version.metadata.name } };
  if (needsArtifactListStaging(version.spec)) {
    spec = structuredClone(version.spec || {});
    delete spec.workflowMetadata;
  }
  const requested = pipelineRoot?.trim() || annotations[ARTIFACT_ROOT];
  // A package without root bindings (hand-written) is submitted as it is.
  if (!requested && annotations[BINDING] !== 'v1') return { annotations, spec };
  const { entries, defaultKey } = await namespaceRepositories(namespace);
  const roots: Record<string, string> = {};
  for (const [key, entry] of Object.entries(entries)) {
    try {
      roots[key] = repositoryRoot(entry);
    } catch {
      // Entries that are not S3/GCS buckets cannot serve pipelines.
    }
  }
  let root: string;
  let key: string | undefined;
  if (requested) {
    const { bucket } = parseRoot(requested);
    key = Object.keys(roots).find((candidate) => roots[candidate] === bucket);
    if (key === undefined)
      throw new Error(
        `No artifact repository in this namespace serves ${bucket}; available: ${[...new Set(Object.values(roots))].sort().join(', ') || 'none'}. Add an entry to the artifact-repositories ConfigMap or choose a served bucket.`,
      );
    root = requested.replace(/\/+$/, '');
  } else {
    if (!defaultKey || !(defaultKey in roots)) {
      if (defaultKey && defaultKey in entries) repositoryRoot(entries[defaultKey]);
      throw new Error(
        'Configure an Argo artifact repository for this namespace (an artifact-repositories ConfigMap with a default entry) before running pipelines.',
      );
    }
    key = defaultKey;
    root = roots[key];
  }
  if (root !== annotations[ARTIFACT_ROOT]?.replace(/\/+$/, '')) {
    if (annotations[BINDING] !== 'v1')
      throw new Error('Recompile this pipeline to enable pipeline-root overrides.');
    const { bucket, prefix } = parseRoot(root);
    Object.assign(annotations, {
      [ARTIFACT_ROOT]: root,
      [BUCKET]: bucket.split('://')[1],
      [PREFIX]: prefix,
    });
  }
  if (key !== defaultKey) spec.artifactRepositoryRef = { key };
  annotations['pipelines.kubeflow.org/pipeline-root'] = root;
  return { annotations, spec };
}
