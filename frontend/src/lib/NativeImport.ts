// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import { load } from 'js-yaml';
import type { NativeResource } from './ArgoResources';
import { PIPELINE, DISPLAY_NAME, DESCRIPTION } from './NativeUi';
import { sanitizeExternalHref } from './UiUtils';

export const VERSION_NAME = 'pipelines.kubeflow.org/version-display-name';
export const VERSION_DESCRIPTION = 'pipelines.kubeflow.org/version-description';
export const CODE_SOURCE = 'pipelines.kubeflow.org/code-source';
export async function importTemplate(
  text: string,
  namespace: string,
  options: {
    pipeline: string;
    displayName: string;
    description: string;
    versionName: string;
    versionDescription: string;
    codeSource: string;
  },
): Promise<NativeResource> {
  const resource = load(text) as NativeResource;
  if (
    resource?.kind !== 'WorkflowTemplate' ||
    resource.apiVersion !== 'argoproj.io/v1alpha1' ||
    !resource.metadata?.labels?.[PIPELINE] ||
    !resource.spec
  )
    throw new Error('Choose a native WorkflowTemplate YAML file compiled with the KFP compiler.');
  if (resource.metadata.namespace && resource.metadata.namespace !== namespace)
    throw new Error(
      `This package targets ${resource.metadata.namespace}. Compile it for ${namespace} before uploading.`,
    );
  if (options.codeSource && !sanitizeExternalHref(options.codeSource))
    throw new Error('Code Source must be an absolute HTTP(S) URL.');
  if (!/^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$/.test(options.pipeline) || options.pipeline.length > 63)
    throw new Error('The pipeline identifier must be a DNS label of at most 63 characters.');
  const bytes = await crypto.subtle.digest(
    'SHA-256',
    new TextEncoder().encode(JSON.stringify([resource.spec, options.versionName])),
  );
  const hash = [...new Uint8Array(bytes)]
    .map((byte) => byte.toString(16).padStart(2, '0'))
    .join('')
    .slice(0, 12);
  return {
    ...resource,
    metadata: {
      name: `${options.pipeline.slice(0, 50).replace(/-+$/, '')}-${hash}`,
      namespace,
      labels: {
        ...resource.metadata.labels,
        [PIPELINE]: options.pipeline,
        'pipelines.kubeflow.org/version': hash,
      },
      annotations: {
        ...resource.metadata.annotations,
        [DISPLAY_NAME]: options.displayName,
        [DESCRIPTION]: options.description,
        [VERSION_NAME]: options.versionName || resource.metadata.name,
        [VERSION_DESCRIPTION]: options.versionDescription,
        ...(options.codeSource ? { [CODE_SOURCE]: options.codeSource } : {}),
      },
    },
  };
}
