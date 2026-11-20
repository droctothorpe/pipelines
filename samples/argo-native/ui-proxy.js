// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
// njs helper for single-user mode: authenticate proxied requests with this pod's
// projected service-account token. It is read per request so kubelet rotation
// takes effect without a restart. Token mode never evaluates this variable.
import fs from 'fs';

const TOKEN = '/var/run/secrets/kubernetes.io/serviceaccount/token';

function serviceAccountAuthorization(r) {
  try {
    const token = fs.readFileSync(TOKEN, 'utf8').trim();
    return token ? 'Bearer ' + token : '';
  } catch (error) {
    r.error('service account token unavailable: ' + error);
    return '';
  }
}

export default { serviceAccountAuthorization };
