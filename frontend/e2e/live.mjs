// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
// Shared setup for the live browser suite: a deployed native installation
// reached through its UI proxy, SDK-created fixtures, and evidence capture.
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdir, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

export const root = fileURLToPath(new URL('../../', import.meta.url));
export const origin =
  process.env.ARGO_UI_URL || process.env.KFP_TEST_HOST || 'http://127.0.0.1:3003';
export const namespace = process.env.ARGO_NAMESPACE || process.env.KFP_TEST_NAMESPACE || 'kfp-argo';
export const editor = process.env.ARGO_EDITOR_TOKEN || process.env.KFP_TEST_TOKEN || '';
export const reader = process.env.ARGO_READER_TOKEN || editor;
export const output = process.env.KFP_UI_OUTPUT || '/tmp/kfp-ui-e2e';
export const channel = process.env.PLAYWRIGHT_CHANNEL || undefined;
export const encode = encodeURIComponent;

export function requireTokens() {
  assert.ok(editor, 'Set ARGO_EDITOR_TOKEN (or KFP_TEST_TOKEN) for the test namespace.');
}

let mode;
/** The proxy's authentication mode; single-user proxies show no token dialog. */
export async function authMode() {
  if (!mode) {
    const response = await fetch(`${origin}/config.json`).catch(() => null);
    mode = response?.ok ? (await response.json()).authMode || 'token' : 'token';
  }
  return mode;
}

// On a multi-user proxy the suite names the user itself, in place of a gateway.
const user = process.env.KFP_TEST_USER;
const identity = user
  ? { [process.env.KFP_TEST_USERID_HEADER || 'kubeflow-userid']: user }
  : undefined;

export async function launch(viewport = { width: 1280, height: 900 }, extraHTTPHeaders = identity) {
  const browser = await chromium.launch({ channel });
  const page = await browser.newPage({ viewport, extraHTTPHeaders });
  const errors = [],
    paths = [],
    urls = [],
    hosts = [];
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('request', (request) => {
    const url = new URL(request.url());
    paths.push(url.pathname);
    urls.push(url.pathname + url.search);
    hosts.push(url.host);
  });
  return { browser, page, errors, paths, urls, hosts };
}

export async function open(page, hash, token = editor) {
  await page.goto(`${origin}/argo.html?namespace=${encode(namespace)}#${hash}`);
  await connect(page, token);
}

export async function connect(page, token = editor) {
  // Single-user proxies hold their own credentials; multi-user proxies take
  // the user from the gateway header and the namespace from the URL.
  if ((await authMode()) === 'token') {
    await page.getByLabel('Kubernetes bearer token').fill(token);
    await page.getByRole('button', { name: 'Connect', exact: true }).click();
    await page.getByRole('dialog').waitFor({ state: 'hidden' });
  }
  await page.locator('#sideNav').waitFor();
}

export function go(page, hash) {
  return page.evaluate((value) => {
    window.location.hash = value;
  }, hash);
}

export async function api(path, options = {}, token = editor) {
  const response = await fetch(origin + path, {
    ...options,
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
      ...identity,
      ...options.headers,
    },
  });
  assert.ok(
    response.ok,
    `${options.method || 'GET'} ${path}: HTTP ${response.status}: ${await (response.ok ? Promise.resolve('') : response.text())}`,
  );
  return response;
}

export async function json(path, options, token) {
  return (await api(path, options, token)).json();
}

/** A run by uid, from the archive (every finished run is persisted there). */
export async function archivedRun(uid, token = reader) {
  // The archive lags the workflow's completion (noticeably on Argo 4.0.x);
  // poll until the record exists rather than failing on the first 404.
  const path = `/argo/api/v1/archived-workflows/${encode(uid)}?namespace=${encode(namespace)}`;
  const deadline = Date.now() + 120000;
  for (;;) {
    const response = await fetch(origin + path, {
      headers: { Authorization: `Bearer ${token}`, ...identity },
    });
    if (response.ok) return response.json();
    if (response.status !== 404 || Date.now() > deadline) {
      assert.fail(`GET ${path}: HTTP ${response.status}: ${await response.text()}`);
    }
    await new Promise((resolve) => setTimeout(resolve, 3000));
  }
}

/**
 * Compiled templates carry artifact keys only and expect the submitter to bind
 * the namespace's repository (`artifact-root-binding: v1`), as the SDK and the
 * UI do. A journey that posts a Workflow itself must bind the same way.
 */
export async function boundArtifactAnnotations(version, token = editor) {
  const keys = [
    'pipelines.kubeflow.org/artifact-repository',
    'pipelines.kubeflow.org/artifact-bucket',
    'pipelines.kubeflow.org/artifact-key-prefix',
    'pipelines.kubeflow.org/artifact-root-binding',
  ];
  const annotations = Object.fromEntries(
    Object.entries(version.metadata.annotations || {}).filter(([key]) => keys.includes(key)),
  );
  if (annotations[keys[3]] !== 'v1' || annotations[keys[0]]) return annotations;
  const repositories = await json(
    `/kubernetes/api/v1/namespaces/${encode(namespace)}/configmaps/artifact-repositories`,
    {},
    token,
  );
  const entry =
    repositories.data[
      repositories.metadata.annotations['workflows.argoproj.io/default-artifact-repository']
    ];
  const bucket = /bucket:\s*['"]?([^'"\s]+)/.exec(entry)?.[1];
  assert.ok(bucket, 'The namespace repository names no bucket');
  return {
    ...annotations,
    [keys[0]]: `s3://${bucket}`,
    [keys[1]]: bucket,
    [keys[2]]: '',
  };
}

export function nodeWithArtifact(run, name) {
  return Object.values(run.status.nodes).find((node) =>
    node.outputs?.artifacts?.some((artifact) => artifact.name === name),
  );
}

export function nodeNamed(run, displayName) {
  return Object.values(run.status.nodes).find((node) => node.displayName === displayName);
}

export async function waitForPhase(name, timeout = 180000, token = editor) {
  const deadline = Date.now() + timeout;
  let run;
  do {
    run = await json(`/argo/api/v1/workflows/${encode(namespace)}/${encode(name)}`, {}, token);
    if (['Succeeded', 'Failed', 'Error'].includes(run.status?.phase)) return run;
    await new Promise((resolve) => setTimeout(resolve, 2000));
  } while (Date.now() < deadline);
  throw new Error(`Timed out waiting for ${name}: ${run.status?.phase}`);
}

export function failures(run) {
  return Object.values(run.status?.nodes || {})
    .filter((node) => ['Failed', 'Error'].includes(node.phase))
    .map((node) => [node.displayName, node.message]);
}

const fixtures = new Map();
/**
 * An SDK-created fixture, made by test/e2e/fixtures.py through the same proxy.
 * Kinds: interop, markdown, classification, preview, validation,
 * nested-importer, optional-version, artifact-list-version, compile:<name>.
 */
export async function fixture(kind) {
  if (!fixtures.has(kind)) {
    await mkdir(join(tmpdir(), 'kfp-ui-e2e'), { recursive: true });
    const path = join(tmpdir(), 'kfp-ui-e2e', `${kind.replace(':', '-')}-${process.pid}.json`);
    execFileSync('uv', ['run', 'python', 'test/e2e/fixtures.py', kind, path], {
      cwd: root,
      encoding: 'utf8',
      timeout: 900000,
      env: {
        ...process.env,
        KFP_TEST_HOST: origin,
        KFP_TEST_NAMESPACE: namespace,
        KFP_TEST_TOKEN: editor,
        PYTHONWARNINGS: 'ignore',
      },
      stdio: ['ignore', 'pipe', 'inherit'],
    });
    fixtures.set(kind, JSON.parse(await readFile(path, 'utf8')));
  }
  return fixtures.get(kind);
}

/** Run a line of SDK client code against the deployment and return its stdout. */
export function sdk(code) {
  const prelude = `import os,sys,kfp; sys.path.insert(0,'test'); from e2e import support; c=support.as_user(kfp.Client(host=os.environ['KFP_TEST_HOST'],namespace=os.environ['KFP_TEST_NAMESPACE'],existing_token=os.environ['KFP_TEST_TOKEN'])); `;
  return execFileSync('uv', ['run', 'python', '-c', prelude + code], {
    cwd: root,
    encoding: 'utf8',
    timeout: 700000,
    env: {
      ...process.env,
      KFP_TEST_HOST: origin,
      KFP_TEST_NAMESPACE: namespace,
      KFP_TEST_TOKEN: editor,
      PYTHONWARNINGS: 'ignore',
    },
  }).trim();
}

export async function shot(page, name, options = {}) {
  await mkdir(output, { recursive: true });
  await page.screenshot({ path: join(output, name + '.png'), animations: 'disabled', ...options });
}

export async function mobile(page, name) {
  const size = page.viewportSize();
  await page.setViewportSize({ width: 390, height: 844 });
  await shot(page, name + '-mobile', { fullPage: true });
  await page.setViewportSize(size);
}
