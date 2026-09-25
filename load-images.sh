#!/usr/bin/env bash
set -euo pipefail
REPORT="$(cd "$(dirname "$0")" && pwd)"
TEMP="$(mktemp -d /tmp/kfp14478-current-images.XXXXXX)"
for image in apiserver persistenceagent scheduledworkflow driver launcher frontend viewer-crd-controller visualization-server; do
  echo "Downloading current application image: $image"
  mkdir -p "$TEMP/$image"
  gh run download 36148418108 --repo kubeflow/pipelines --name "$image" --dir "$TEMP/$image"
  docker --context orbstack load -i "$TEMP/$image/$image.tar"
  docker --context orbstack tag "kind-registry:5000/$image:latest" "kfp-pr14478/$image:c390c597e"
  docker --context orbstack image inspect "kfp-pr14478/$image:c390c597e" --format '{{.RepoTags}} {{.Id}} {{.Os}}/{{.Architecture}}' | tee -a "$REPORT/evidence/images.txt"
  rm "$TEMP/$image/$image.tar"
done
rmdir "$TEMP"/* "$TEMP"
