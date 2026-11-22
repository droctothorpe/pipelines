// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
// Multi-user authorization mapping of the UI proxy: node --test samples/argo-native
import assert from 'node:assert/strict';
import { test } from 'node:test';
import proxy from './ui-proxy.js';

const attributes = (method, uri) => proxy.resourceAttributes(method, uri);
const argo = (verb, resource, namespace, name = '') => ({
  namespace,
  verb,
  group: 'argoproj.io',
  resource,
  name,
});

test('Kubernetes paths map to their resource, verb and namespace', () => {
  assert.deepEqual(attributes('GET', '/kubernetes/api/v1/namespaces/team/configmaps?labelSelector=a'), {
    namespace: 'team',
    verb: 'list',
    group: '',
    resource: 'configmaps',
    name: '',
    subresource: '',
  });
  assert.deepEqual(attributes('PUT', '/kubernetes/api/v1/namespaces/team/configmaps/exp-1'), {
    namespace: 'team',
    verb: 'update',
    group: '',
    resource: 'configmaps',
    name: 'exp-1',
    subresource: '',
  });
  assert.deepEqual(attributes('GET', '/kubernetes/api/v1/namespaces/team/pods/p/log?container=main'), {
    namespace: 'team',
    verb: 'get',
    group: '',
    resource: 'pods',
    name: 'p',
    subresource: 'log',
  });
  assert.deepEqual(
    attributes('PATCH', '/kubernetes/apis/argoproj.io/v1alpha1/namespaces/team/workflows/run-1'),
    { ...argo('patch', 'workflows', 'team', 'run-1'), subresource: '' },
  );
  assert.deepEqual(
    attributes('GET', '/kubernetes/apis/argoproj.io/v1alpha1/namespaces/team/workflows?watch=true'),
    { ...argo('watch', 'workflows', 'team'), subresource: '' },
  );
});

test('cluster-wide Kubernetes requests carry an empty namespace, which tenant roles never grant', () => {
  assert.equal(attributes('GET', '/kubernetes/apis/argoproj.io/v1alpha1/workflows').namespace, '');
  assert.equal(attributes('GET', '/kubernetes/api/v1/namespaces').namespace, '');
  assert.equal(attributes('GET', '/kubernetes/api/v1/namespaces/team'), null);
});

test('Argo Server paths map to the Kubernetes resources behind them', () => {
  assert.deepEqual(attributes('GET', '/argo/api/v1/workflows/team?listOptions.limit=20'), argo('list', 'workflows', 'team'));
  assert.deepEqual(attributes('GET', '/argo/api/v1/workflows/team/run-1'), argo('get', 'workflows', 'team', 'run-1'));
  assert.deepEqual(attributes('GET', '/argo/api/v1/workflows/team/run-1/log?podName=x'), argo('get', 'workflows', 'team', 'run-1'));
  assert.deepEqual(attributes('PUT', '/argo/api/v1/workflows/team/run-1/terminate'), argo('update', 'workflows', 'team', 'run-1'));
  assert.deepEqual(attributes('PUT', '/argo/api/v1/workflows/team/run-1/retry'), argo('update', 'workflows', 'team', 'run-1'));
  assert.deepEqual(attributes('POST', '/argo/api/v1/workflows/team'), argo('create', 'workflows', 'team'));
  assert.deepEqual(attributes('DELETE', '/argo/api/v1/workflows/team/run-1'), argo('delete', 'workflows', 'team', 'run-1'));
  assert.deepEqual(attributes('GET', '/argo/api/v1/workflow-templates/team'), argo('list', 'workflowtemplates', 'team'));
  assert.deepEqual(attributes('POST', '/argo/api/v1/workflow-templates/team'), argo('create', 'workflowtemplates', 'team'));
  assert.deepEqual(attributes('PUT', '/argo/api/v1/cron-workflows/team/s/suspend'), argo('update', 'cronworkflows', 'team', 's'));
  assert.deepEqual(attributes('GET', '/argo/api/v1/workflows/a%2Fb/x'), argo('get', 'workflows', 'a/b', 'x'));
});

test('archived workflows need a namespace to list and a uid lookup to read', () => {
  assert.deepEqual(
    attributes('GET', '/argo/api/v1/archived-workflows?namespace=team&listOptions.limit=5'),
    argo('list', 'workflows', 'team'),
  );
  assert.equal(attributes('GET', '/argo/api/v1/archived-workflows'), null);
  assert.equal(attributes('GET', '/argo/api/v1/archived-workflows?listOptions.limit=5'), null);
  assert.deepEqual(attributes('GET', '/argo/api/v1/archived-workflows/uid-1?namespace=team'), {
    archived: 'uid-1',
    verb: 'get',
    namespace: 'team',
  });
  assert.deepEqual(attributes('DELETE', '/argo/api/v1/archived-workflows/uid-1'), {
    archived: 'uid-1',
    verb: 'delete',
    namespace: '',
  });
  assert.deepEqual(attributes('PUT', '/argo/api/v1/archived-workflows/uid-1/retry'), {
    archived: 'uid-1',
    verb: 'create',
    namespace: '',
  });
  assert.deepEqual(
    attributes('GET', '/argo/artifact-files/team/archived-workflows/uid-1/node/outputs/model'),
    { archived: 'uid-1', verb: 'get', namespace: 'team' },
  );
});

test('artifact downloads are reads of the workflow that produced them', () => {
  assert.deepEqual(attributes('GET', '/argo/artifacts/team/run-1/node/model'), argo('get', 'workflows', 'team', 'run-1'));
  assert.deepEqual(
    attributes('GET', '/argo/artifact-files/team/workflows/run-1/node/outputs/model'),
    argo('get', 'workflows', 'team', 'run-1'),
  );
  assert.equal(attributes('POST', '/argo/artifacts/team/run-1/node/model'), null);
});

test('everything the UI and SDK never call is refused', () => {
  for (const [method, uri] of [
    ['GET', '/argo/artifacts-by-uid/uid-1/node/model'],
    ['GET', '/argo/input-artifacts/team/run-1/node/model'],
    ['GET', '/argo/api/v1/cluster-workflow-templates'],
    ['GET', '/argo/api/v1/workflow-events/team'],
    ['GET', '/argo/api/v1/workflows'],
    ['GET', '/argo/oauth2/redirect'],
    ['GET', '/kubernetes/apis/'],
    ['GET', '/kubernetes/api/v1/namespaces/team/pods/p/exec/extra'],
    ['GET', '/kubernetes/openapi/v2'],
    ['OPTIONS', '/argo/api/v1/workflows/team'],
    ['GET', '/argo/api/v1/workflows/%E0%A4%A'],
  ]) {
    assert.equal(attributes(method, uri), null, `${method} ${uri}`);
  }
});

test('the identity header is used once, exactly, with its configured prefix stripped', () => {
  assert.equal(proxy.identity({ 'kubeflow-userid': 'alice@example.com' }, 'kubeflow-userid', ''), 'alice@example.com');
  assert.equal(
    proxy.identity({ 'x-goog-authenticated-user-email': 'accounts.google.com:bob@example.com' }, 'x-goog-authenticated-user-email', 'accounts.google.com:'),
    'bob@example.com',
  );
  assert.equal(proxy.identity({ 'kubeflow-userid': 'bob@example.com' }, 'kubeflow-userid', 'accounts.google.com:'), '');
  assert.equal(proxy.identity({ 'kubeflow-userid': 'a@x.io,b@x.io' }, 'kubeflow-userid', ''), '');
  assert.equal(proxy.identity({}, 'kubeflow-userid', ''), '');
  assert.equal(proxy.identity({ 'kubeflow-userid': '' }, 'kubeflow-userid', ''), '');
});
