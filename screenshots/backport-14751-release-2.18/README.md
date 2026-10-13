# Backport 14751 screenshots

Screenshots for PR #14864 (`release-2.18` backport of #14751).

Captured on 2026-10-13 from a local OrbStack Kubernetes deployment after updating `kubeflow/ml-pipeline-ui` to image `kfp-backport-14751/frontend:16cf6435e` built from commit `16cf6435e`.

Routes used:

- `#/runs/details/917b63a7-6701-4e18-85a5-8227006d92fd` — `inline-subdag-run.png`
- `#/runs/details/9ec167af-b0fe-4b8f-9f18-53db71808ac8` — `nested-loops-run.png`
- `#/runs/details/103b0402-26cd-4eb5-ac02-f3209a8c2958` — `multi-layer-run.png`

These captures show the backported inline grouped sub-DAG rendering in the deployed `release-2.18` UI.
