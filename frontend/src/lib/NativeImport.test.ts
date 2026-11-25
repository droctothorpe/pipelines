// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import { webcrypto } from 'node:crypto';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { importTemplate, VERSION_NAME } from './NativeImport';
const resource = {
  apiVersion: 'argoproj.io/v1alpha1',
  kind: 'WorkflowTemplate',
  metadata: {
    name: 'compiled-version',
    namespace: 'team',
    uid: 'old-uid',
    resourceVersion: 'old-version',
    ownerReferences: [{ uid: 'old-owner' }],
    labels: { 'pipelines.kubeflow.org/pipeline': 'compiled' },
  },
  spec: {
    entrypoint: 'main',
    templates: [{ name: 'main', container: { image: 'image@sha256:abc', command: ['python'] } }],
  },
};
const options = {
  pipeline: 'human-pipeline',
  displayName: 'Human pipeline',
  description: 'Description',
  versionName: 'Version one',
  versionDescription: 'Changes',
  codeSource: 'https://example.com/source',
};
beforeEach(() => vi.stubGlobal('crypto', webcrypto));
afterEach(() => vi.unstubAllGlobals());
describe('stock upload form native import', () => {
  it('creates stable content-named versions without changing execution or copying server identity', async () => {
    const result = await importTemplate(JSON.stringify(resource), 'team', options);
    expect(result.metadata.name).toMatch(/^human-pipeline-[a-f0-9]{12}$/);
    expect(result.spec).toEqual(resource.spec);
    expect(result.metadata.uid).toBeUndefined();
    expect(result.metadata.resourceVersion).toBeUndefined();
    expect(result.metadata).not.toHaveProperty('ownerReferences');
    expect(result.metadata.annotations?.[VERSION_NAME]).toBe('Version one');
    expect(await importTemplate(JSON.stringify(resource), 'team', options)).toEqual(result);
    expect(
      (
        await importTemplate(JSON.stringify(resource), 'team', {
          ...options,
          versionName: 'Version two',
        })
      ).metadata.name,
    ).not.toBe(result.metadata.name);
  });
  it('does not silently relocate explicitly namespaced packages', async () => {
    await expect(importTemplate(JSON.stringify(resource), 'another', options)).rejects.toThrow(
      'Compile it for another',
    );
  });
  it.each(['javascript:alert(1)', '//example.com', 'data:text/html,test'])(
    'rejects unsafe code source %s',
    async (codeSource) => {
      await expect(
        importTemplate(JSON.stringify(resource), 'team', { ...options, codeSource }),
      ).rejects.toThrow('absolute HTTP(S)');
    },
  );
  it('rejects a retired IR package rather than fabricating a native resource', async () => {
    await expect(
      importTemplate('{"pipelineInfo":{"name":"old"}}', 'team', options),
    ).rejects.toThrow('native WorkflowTemplate');
  });
  it('keeps long version resource names inside Kubernetes DNS limits', async () => {
    const imported = await importTemplate(JSON.stringify(resource), 'team', {
      ...options,
      pipeline: 'a'.repeat(63),
    });
    expect(imported.metadata.name.length).toBeLessThanOrEqual(63);
  });
});
