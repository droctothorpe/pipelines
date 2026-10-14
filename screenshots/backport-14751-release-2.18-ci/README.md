# PR #14864 — matching release-2.18 CI deployment

Captured 2026-10-14 before review-fix commit `c12c7d095`.

- PR head used by CI: `16cf6435eda015012ebb46e98fae714db5b9cf35`.
- Image artifact producer: https://github.com/kubeflow/pipelines/actions/runs/38484351493
- All 12 KFP component images were downloaded as Docker tar artifacts, loaded without rebuilding, and tagged `kfp-ci-14864/<component>:38484351493`.
- Images are AMD64, running under OrbStack emulation. The fresh installation uses the release-2.18 manifests and new database/object-store volumes.
- Frontend image ID: `sha256:855975719c17d7c3043ff725dfb2e5098711c72fdb6dc7d36a2682f38522a396`.
- CI images omit embedded commit metadata; the UI therefore displays `Version: unknown`. Provenance comes from the CI run and loaded image IDs, not the health endpoint.
- SeaweedFS local arguments: `-master.volumeSizeLimitMB=64 -volume.max=32` to fit the local disk budget.

`nested-artifacts-graph.png` is an unmodified full-page screenshot of run `9e3ea8e6-7ce9-4aa2-aa0b-fc2cde5b1d43` (CI 2.18 — nested artifacts), which reached SUCCEEDED. Green execution/group statuses come from MLMD, not mocked responses. Node details were separately checked for populated parameters, artifact URIs/content and Complete status; this screenshot shows the graph, not the side panel.

Data-passing run `e0b5de08-308d-4330-ac21-759a1015c644` and parallel-artifact run `ac696ef1-79cb-4871-8a29-cca577a3d08e` also reached SUCCEEDED. The older nested-loop fixture `2473e287-2598-4b93-9eb2-3755d44ccb93` failed on a parameter-expression selector and is not claimed as successful validation. A browser check encountered missing Ace `worker-json.js` errors while displaying JSON output; the values rendered, but the browser check was not error-free.

This replaces the earlier cropped static graphs from the mismatched newer-backend deployment. No screenshots were captured after the user requested validation stop.
