// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import { load } from 'js-yaml';
import { argoRequest, ArgoRequestError } from './Argo';

const MARKER = 'pipelines.kubeflow.org/artifact-list-staging';
const BOUND = 'pipelines.kubeflow.org/staging-secret-volumes';
const INIT = 'kfp-stage-artifacts';
type Spec = Record<string, any>;

export const needsArtifactListStaging = (spec?: Spec) =>
  (spec?.templates || []).some((t: Spec) => t.metadata?.annotations?.[MARKER] === 'v1');

/** Resolve namespace configuration, never Secret values; keep the version immutable. */
export async function prepareArtifactLists(namespace: string, original: Spec): Promise<Spec> {
  if (!needsArtifactListStaging(original)) return original;
  const spec = structuredClone(original);
  const getMap = async (name: string) =>
    (
      await argoRequest(
        `/kubernetes/api/v1/namespaces/${encodeURIComponent(namespace)}/configmaps/${encodeURIComponent(name)}`,
      )
    ).json();
  const reference = spec.artifactRepositoryRef;
  let config: Spec;
  try {
    config = await getMap(reference?.configMap || 'artifact-repositories');
  } catch (error) {
    if (reference !== undefined || !(error instanceof ArgoRequestError) || error.status !== 404)
      throw error;
    config = {};
  }
  const key =
    reference?.key ||
    config.metadata?.annotations?.['workflows.argoproj.io/default-artifact-repository'];
  let text;
  if (key) text = config.data?.[key];
  else if (reference !== undefined)
    throw new Error('Artifact repository reference needs a key or a namespace default annotation.');
  else text = (await getMap('workflow-controller-configmap')).data?.artifactRepository;
  if (!text)
    throw new Error(
      'Configure an Argo artifact repository before submitting artifact-list consumers.',
    );
  const parsed = load(text);
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed))
    throw new Error('Argo artifact repository configuration must be an object.');
  if ('plugin' in parsed)
    throw new Error(
      'Artifact-list staging does not yet support repository plugins; use a native S3/GCS repository.',
    );
  const repository = Object.fromEntries(
    Object.entries(parsed).filter(([key]) => ['s3', 'gcs'].includes(key)),
  );
  const secrets = new Map<string, Set<string>>();
  for (const config of Object.values(repository)) {
    if (!config || typeof config !== 'object' || Array.isArray(config))
      throw new Error('Invalid artifact-repository configuration.');
    for (const [field, selector] of Object.entries(config)) {
      if (!field.endsWith('Secret') || !selector) continue;
      if (typeof selector !== 'object' || !('name' in selector) || !('key' in selector))
        throw new Error('Invalid artifact-repository Secret selector.');
      const { name, key } = selector;
      if (
        typeof name !== 'string' ||
        typeof key !== 'string' ||
        !/^[a-z0-9][a-z0-9.-]*$/.test(name) ||
        !/^[A-Za-z0-9_.-]+$/.test(key) ||
        ['.', '..'].includes(key)
      )
        throw new Error('Invalid artifact-repository Secret selector.');
      if (!secrets.has(name)) secrets.set(name, new Set());
      secrets.get(name)!.add(key);
    }
  }
  for (const template of spec.templates) {
    const annotations = template.metadata?.annotations || {};
    if (annotations[MARKER] !== 'v1') continue;
    const init = template.initContainers.find((c: Spec) => c.name === INIT);
    const previous = new Set(JSON.parse(annotations[BOUND] || '[]'));
    template.volumes = (template.volumes || []).filter((v: Spec) => !previous.has(v.name));
    init.volumeMounts = init.volumeMounts.filter((v: Spec) => !previous.has(v.name));
    const bound = [];
    for (const [index, name] of [...secrets.keys()].sort().entries()) {
      const volume = 'kfp-stage-secret-' + index;
      if (template.volumes.some((v: Spec) => v.name === volume))
        throw new Error('Artifact staging volume conflicts with an existing volume.');
      template.volumes.push({
        name: volume,
        secret: {
          secretName: name,
          items: [...secrets.get(name)!].sort().map((key) => ({ key, path: key })),
        },
      });
      init.volumeMounts.push({ name: volume, mountPath: '/argo/secret/' + name, readOnly: true });
      bound.push(volume);
    }
    annotations[BOUND] = JSON.stringify(bound);
    init.env.find((e: Spec) => e.name === 'KFP_STAGING_REPOSITORY').value =
      JSON.stringify(repository);
  }
  return spec;
}
