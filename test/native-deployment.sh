#!/usr/bin/env bash
# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail
cd "$(dirname "$0")/.."
cluster=native-kfp
namespace=kfp-argo
kubeconfig=$(mktemp)
export KUBECONFIG="$kubeconfig"
kind create cluster --name "$cluster" --kubeconfig "$kubeconfig" --wait 120s
forward_pid=''
cleanup() {
  if [[ -n "$forward_pid" ]]; then kill "$forward_pid" 2>/dev/null || true; fi
  kind delete cluster --name "$cluster"
  rm -f "$kubeconfig"
}
trap cleanup EXIT
context="kind-$cluster"
port=${KFP_TEST_PORT:-$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')}
uv build --package kfp --wheel
npm --prefix frontend run build
docker build -f samples/argo-native/Dockerfile -t kfp-argo-demo:dev .
docker build -f samples/argo-native/Dockerfile.ui -t kfp-argo-ui:test .
uv run python samples/argo-native/compile_demo.py --output /tmp/native-version.yaml
image_digest=$(docker image inspect kfp-argo-demo:dev --format '{{.Id}}')
image="kfp-argo-demo:kfp-${image_digest#sha256:}"
kind load docker-image --name "$cluster" "$image" kfp-argo-ui:test
uv run python samples/argo-native/deploy.py --namespace "$namespace" --ui-image kfp-argo-ui:test > /tmp/native-install.yaml
kubectl --context "$context" -n "$namespace" apply --server-side -f /tmp/native-install.yaml
for deployment in postgres minio workflow-controller argo-server kfp-argo-ui; do
  kubectl --context "$context" -n "$namespace" rollout status "deployment/$deployment" --timeout=180s
done
kubectl --context "$context" -n "$namespace" apply -f /tmp/native-version.yaml
forward() {
  if [[ -n "$forward_pid" ]]; then kill "$forward_pid" 2>/dev/null || true; wait "$forward_pid" 2>/dev/null || true; fi
  kubectl --context "$context" -n "$namespace" port-forward svc/kfp-argo-ui "$port:80" > /tmp/native-port-forward.log 2>&1 &
  forward_pid=$!
  for _ in $(seq 1 60); do
    kill -0 "$forward_pid"
    if grep -q 'Forwarding from 127.0.0.1:' /tmp/native-port-forward.log && curl -fsS "http://127.0.0.1:$port/argo.html" -o /dev/null; then return; fi
    sleep 1
  done
}
forward
# Argo Server itself, for the direct-Kubernetes client's archive reads.
argo_port=$((port + 1))
kubectl --context "$context" -n "$namespace" port-forward svc/argo-server "$argo_port:2746" > /tmp/native-argo-port-forward.log 2>&1 &
export ARGO_EDITOR_TOKEN ARGO_READER_TOKEN
ARGO_EDITOR_TOKEN=$(kubectl --context "$context" -n "$namespace" create token argo-ui-editor --duration=2h)
ARGO_READER_TOKEN=$(kubectl --context "$context" -n "$namespace" create token argo-ui-reader --duration=2h)
if [[ ${GITHUB_ACTIONS:-} == true ]]; then
  printf '::add-mask::%s\n' "$ARGO_EDITOR_TOKEN" "$ARGO_READER_TOKEN"
fi
export ARGO_SERVER="127.0.0.1:$port" ARGO_UI_URL="http://127.0.0.1:$port" ARGO_BASE_HREF=/argo ARGO_HTTP1=true ARGO_SECURE=false
export ARGO_TOKEN="Bearer $ARGO_EDITOR_TOKEN"
# The live suite, SDK end to end against this cluster: everything but cases that
# need hardware or credentials, in parallel, with the content-addressed demo
# image so pods carry this SDK instead of installing it.
KFP_TEST_HOST="http://127.0.0.1:$port" KFP_TEST_NAMESPACE="$namespace" KFP_TEST_TOKEN="$ARGO_EDITOR_TOKEN" \
  KFP_TEST_IMAGE="$image" KFP_TEST_CONTEXT="$context" KFP_TEST_ARGO_SERVER="https://127.0.0.1:$argo_port" \
  uv run python -m pytest test/e2e -m 'not prerequisite' -n "${KFP_TEST_WORKERS:-4}" --dist loadfile \
  -p no:randomly --e2e-output /tmp/kfp-e2e -q
export ARGO_CONTEXT="$context" ARGO_NAMESPACE="$namespace"
export ARGO_VERSION_NAME
ARGO_VERSION_NAME=$(uv run python -c "import yaml; print(yaml.safe_load(open('/tmp/native-version.yaml'))['metadata']['name'])")
export PLAYWRIGHT_CHANNEL=${PLAYWRIGHT_CHANNEL:-chromium}
# The live browser suite shares the cluster and its SDK-created fixtures, then
# the deployment acceptance test runs alone because it restarts services.
(cd frontend && npm run test:e2e)
node --test frontend/e2e/deployment.test.mjs

# Multi-user mode on the same cluster: Argo runs cluster-wide, a tenant namespace
# is prepared, and the proxy authorizes the user named by the gateway header. The
# suite sets that header itself, as stock's multi-user tests do.
tenant=kfp-tenant-a
uv run python samples/argo-native/deploy.py --namespace "$namespace" --ui-image kfp-argo-ui:test --auth-mode multi-user > /tmp/native-multi-user.yaml
kubectl --context "$context" -n "$namespace" apply --server-side --force-conflicts -f /tmp/native-multi-user.yaml
for deployment in workflow-controller argo-server kfp-argo-ui; do
  kubectl --context "$context" -n "$namespace" rollout status "deployment/$deployment" --timeout=180s
done
kubectl --context "$context" create namespace "$tenant"
uv run python samples/argo-native/deploy.py --namespace "$namespace" --tenant "$tenant" | kubectl --context "$context" apply --server-side -f -
kubectl --context "$context" apply -f test/e2e/multi-user-roles.yaml
# The tenant keeps its own bucket: Argo's repository chain is the namespace
# storage policy, and runs there must land in it.
kubectl --context "$context" -n "$namespace" exec deploy/minio -- mkdir -p "/data/$tenant"
kubectl --context "$context" -n "$tenant" get configmap artifact-repositories -o json \
  | sed "s/bucket: argo-artifacts/bucket: $tenant/g" \
  | kubectl --context "$context" -n "$tenant" apply --server-side --force-conflicts -f -
forward
KFP_TEST_HOST="http://127.0.0.1:$port" KFP_TEST_NAMESPACE="$namespace" KFP_TEST_TOKEN=gateway KFP_TEST_TENANT="$tenant" \
  KFP_TEST_IMAGE="$image" \
  uv run python -m pytest test/e2e/test_multi_user.py -p no:randomly --e2e-output /tmp/kfp-e2e/multi-user -q
# The dashboard journeys, then the stock lifecycle and SDK round trips as a tenant editor.
ARGO_NAMESPACE="$tenant" ARGO_EDITOR_TOKEN=gateway KFP_TEST_USER=alice@example.com \
  node --test frontend/e2e/multi-user.test.mjs frontend/e2e/pipeline-lifecycle.test.mjs frontend/e2e/sdk-ui-interop.test.mjs
