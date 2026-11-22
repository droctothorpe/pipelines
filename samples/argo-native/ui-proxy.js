// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
// njs helpers for the UI proxy.
//
// single-user: proxied requests carry this pod's projected service-account
// token. It is read per request so kubelet rotation takes effect without a
// restart.
//
// multi-user: the authenticating gateway (Kubeflow's Istio ingress with
// oauth2-proxy, or any front proxy that sets an identity header) names the user.
// Every proxied request is authorized for that user with a SubjectAccessReview
// on the Kubernetes resource it reaches, then forwarded with the proxy's own
// token. This is the stock API server's model: the user is checked, the system
// account acts. Paths the UI and SDK do not use are denied.
import fs from 'fs';

const TOKEN = '/var/run/secrets/kubernetes.io/serviceaccount/token';
const VERBS = { GET: 'get', HEAD: 'get', POST: 'create', PUT: 'update', PATCH: 'patch', DELETE: 'delete' };
// Argo Server paths without a namespace that reveal nothing about a tenant.
const OPEN = ['/argo/api/v1/info', '/argo/api/v1/version', '/argo/api/v1/userinfo'];
const ARGO_RESOURCES = {
  workflows: 'workflows',
  'workflow-templates': 'workflowtemplates',
  'cron-workflows': 'cronworkflows',
};

function serviceAccountAuthorization(r) {
  try {
    const token = fs.readFileSync(TOKEN, 'utf8').trim();
    return token ? 'Bearer ' + token : '';
  } catch (error) {
    r.error('service account token unavailable: ' + error);
    return '';
  }
}

function decode(segment) {
  try {
    return decodeURIComponent(segment);
  } catch (error) {
    return null;
  }
}

function split(uri) {
  const index = uri.indexOf('?');
  const path = index < 0 ? uri : uri.slice(0, index);
  const query = {};
  (index < 0 ? '' : uri.slice(index + 1)).split('&').forEach((pair) => {
    const eq = pair.indexOf('=');
    if (eq > 0) query[decode(pair.slice(0, eq))] = decode(pair.slice(eq + 1));
  });
  const segments = path.split('/').filter((segment) => segment !== '');
  const decoded = segments.map(decode);
  return { segments: decoded.indexOf(null) < 0 ? decoded : null, query };
}

function readVerb(method, query, named) {
  if (method !== 'GET' && method !== 'HEAD') return VERBS[method];
  if (named) return 'get';
  return query.watch === 'true' || query['listOptions.watch'] === 'true' ? 'watch' : 'list';
}

/**
 * The Kubernetes resource a proxied request reaches, as SubjectAccessReview
 * attributes, or null when the request is not one the UI or SDK makes. An
 * archived workflow addressed by uid returns {archived: uid, namespace} instead:
 * the caller must look the namespace up before authorizing.
 */
function resourceAttributes(method, uri) {
  const verb = VERBS[method];
  const request = split(uri);
  if (!verb || !request.segments) return null;
  const s = request.segments;
  if (s[0] === 'kubernetes') {
    let rest;
    let group = '';
    if (s[1] === 'api' && s[2] === 'v1') rest = s.slice(3);
    else if (s[1] === 'apis' && s.length > 4) {
      group = s[2];
      rest = s.slice(4);
    } else return null;
    let namespace = '';
    if (rest[0] === 'namespaces' && rest.length > 1) {
      namespace = rest[1];
      rest = rest.slice(2);
    }
    if (rest.length === 0 || rest.length > 3) return null;
    return {
      namespace,
      verb: readVerb(method, request.query, rest.length > 1),
      group,
      resource: rest[0],
      name: rest[1] || '',
      subresource: rest[2] || '',
    };
  }
  if (s[0] !== 'argo') return null;
  if (s[1] === 'api' && s[2] === 'v1') {
    const kind = s[3];
    if (kind === 'archived-workflows') {
      if (s.length > 6) return null;
      if (s.length === 4) {
        const namespace = request.query.namespace || '';
        return namespace
          ? { namespace, verb: readVerb(method, request.query, false), group: 'argoproj.io', resource: 'workflows', name: '' }
          : null;
      }
      return { archived: s[4], verb: s.length === 6 ? 'create' : verb, namespace: request.query.namespace || '' };
    }
    const resource = ARGO_RESOURCES[kind];
    if (!resource || s.length < 5 || s.length > 7) return null;
    return {
      namespace: s[4],
      verb: readVerb(method, request.query, s.length > 5),
      group: 'argoproj.io',
      resource,
      name: s[5] || '',
    };
  }
  if (s[1] === 'artifacts' && s.length === 6 && verb === 'get') {
    return { namespace: s[2], verb: 'get', group: 'argoproj.io', resource: 'workflows', name: s[3] };
  }
  if (s[1] === 'artifact-files' && s.length === 8 && verb === 'get') {
    if (s[3] === 'workflows') {
      return { namespace: s[2], verb: 'get', group: 'argoproj.io', resource: 'workflows', name: s[4] };
    }
    if (s[3] === 'archived-workflows') return { archived: s[4], verb: 'get', namespace: s[2] };
  }
  return null;
}

/** The user named by the gateway, or '' when the header is missing or malformed. */
function identity(headers, name, prefix) {
  const value = headers[name];
  if (typeof value !== 'string' || !value || value.indexOf(',') >= 0) return '';
  if (prefix && value.indexOf(prefix) !== 0) return '';
  return prefix ? value.slice(prefix.length) : value;
}

function review(r, user, attributes) {
  const body = JSON.stringify({
    apiVersion: 'authorization.k8s.io/v1',
    kind: 'SubjectAccessReview',
    spec: { user, resourceAttributes: attributes },
  });
  return r.subrequest('/_kfp/subjectaccessreview', { method: 'POST', body }).then((reply) => {
    if (reply.status !== 201 && reply.status !== 200) {
      r.error('SubjectAccessReview failed: HTTP ' + reply.status);
      return 502;
    }
    const status = JSON.parse(reply.responseText).status || {};
    return status.allowed && !status.denied ? 204 : 403;
  });
}

/** auth_request handler: 204 allows the proxied request, 401/403 refuse it. */
function authorize(r) {
  if (r.variables.kfp_auth_mode !== 'multi-user') {
    r.return(204);
    return;
  }
  const user = identity(r.headersIn, r.variables.kfp_userid_header, r.variables.kfp_userid_prefix);
  if (!user) {
    r.return(401);
    return;
  }
  // The proxied path as rewritten by nginx: a /pipeline/ prefix is already gone.
  const uri = r.variables.kfp_target_uri || r.variables.request_uri;
  if (OPEN.indexOf(uri.split('?')[0]) >= 0) {
    r.return(204);
    return;
  }
  const target = resourceAttributes(r.variables.request_method, uri);
  if (!target) {
    r.return(403);
    return;
  }
  let decision;
  if (target.archived) {
    // Argo looks archived workflows up by uid alone, so the namespace the
    // caller claims must be the one the archive recorded.
    decision = r
      .subrequest('/_kfp/archive/' + encodeURIComponent(target.archived))
      .then((reply) => {
        // auth_request turns anything but 2xx/401/403 into a 500, so an unknown
        // uid is refused like a foreign one.
        if (reply.status === 404) return 403;
        if (reply.status !== 200) {
          r.error('archive lookup failed: HTTP ' + reply.status);
          return 502;
        }
        const namespace = ((JSON.parse(reply.responseText) || {}).metadata || {}).namespace;
        if (!namespace || (target.namespace && target.namespace !== namespace)) return 403;
        return review(r, user, { namespace, verb: target.verb, group: 'argoproj.io', resource: 'workflows' });
      });
  } else {
    decision = review(r, user, target);
  }
  decision
    .then((status) => r.return(status))
    .catch((error) => {
      r.error('authorization failed: ' + error);
      r.return(502);
    });
}

export default { serviceAccountAuthorization, authorize, resourceAttributes, identity };
