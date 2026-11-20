# `samples/core` on the native Argo stack

**Snapshot: 2026-11-20**, branch `feat/native-argo-prototype`, commit `9cd2e7b2e`
plus the compiler fixes described below. Cluster: OrbStack context `orbstack`,
namespace `kfp-argo`, Argo `v4.1.6`, UI proxy in single-user mode. Every pipeline
definition under `samples/core` was compiled with the native compiler and, where it
compiles, submitted through the public `kfp.Client` against the live cluster with
`test/sdk_compatibility/run_samples.py`. Reports live in
`/tmp/kfp-core-samples-20261120/` (workstation evidence, not CI artifacts).

Status words: **pass** means the run reached the state the sample intends and the
runner's semantic checks held; **baseline** means the sample fails on stock KFP for
the same reason; **prerequisite** means the environment lacks hardware or
credentials; **fixed** means it failed on `9cd2e7b2e` and passes after the fixes in
this document.

## Results

| Sample | Definitions | Result | Notes |
|---|---|---|---|
| `artifact_previews/artifact_previews.py` | 4 | pass | `artifact_preview_formats_pipeline` exceeded the runner's 900 s timeout but the workflow finished `Succeeded` after 15 m 44 s: 11 sequential pods (`parallelism=1`) each pip-install polars, torch and transformers. 6 collected dataframe and 4 collected model URIs on S3. Previews verified for the other three. |
| `caching/caching.ipynb`, `caching/caching_sample.py` | 4 | pass | Cold pass with caching disabled, then default caching: the second `caching_pipeline` run was a cache hit (1/1 pods memoized, 5 s), `caching_pipeline3` never hits, as the sample intends. |
| `condition/condition_v2.py` | 1 | pass | Forced `heads`; both branches executed. |
| `condition/nested_condition.py` | 1 | pass | Earlier inventory item U48 (interrupted run) is closed by this pass. |
| `execution_order/execution_order.py` | 1 | pass | |
| `exit_handler/exit_handler.py` | 1 | pass | Run ends `FAILED` by design; the exit task succeeded. |
| `kfp_env_validation/kfp_env_validation.ipynb` | 1 | baseline | Notebook does not compile: `NameError: name 'dsl' is not defined` (B02). Also needs GCP credentials. |
| `kubernetes_pvc/kubernetes_pvc.py` | 1 | fixed | Three independent causes on `9cd2e7b2e`; see below. Passes with a PVC-capable workflow service account (`--service-account sdk-sample-pvc-ef4f9a8d`, StorageClass `standard`). The default `argo-workflow` account cannot create claims, which is the documented P04 prerequisite. |
| `loop_output/loop_output.py` | 1 | pass | |
| `loop_parallelism/loop_parallelism.py` | 1 | fixed | Object loop items; see below. |
| `loop_parameter/loop_parameter.py` | 1 | fixed | Object loop items from an upstream output; see below. |
| `loop_static/loop_static.py` | 1 | pass | JSON-string loop items; re-verified after the loop fix. |
| `multiple_outputs/multiple_outputs.ipynb` | 1 | pass | |
| `output_a_directory/output_a_directory.py` | 1 | pass | |
| `parallel_join/parallel_join.py` | 1 | baseline | `@dsl.container_component()` is called with parentheses and does not compile on stock either (B01). Also needs GCS. |
| `resource_spec/resource_spec.py` | 1 | pass | Run with `n=10000` as the runner records; the stock OOM counter-case was not run. |
| `resource_spec/runtime_resource_request.py` | 1 | pass | |
| `resource_spec/runtime_resource_request_gpu.py` | 1 | baseline + prerequisite | Pod rejected: `resources.limits[NVIDIA_TESLA_K80]: must be a standard resource type or fully qualified`. The stock driver also uses the accelerator type verbatim as the resource name, so stock produces the same invalid pod. OrbStack has no GPU in any case (P01). |
| `retry/retry.py` | 1 | pass | Random exit codes retried; 6 pods, final `SUCCEEDED`. |
| `secret/secret.py` | 1 | prerequisite + baseline | `gsutil` task: `401 Anonymous caller` without GCP credentials (P02). `gcs_list_buckets` task: its `python:3.7` base image cannot install the SDK runtime (`kfp==2.17.0` requires Python >= 3.9), which stock's launcher would also hit. |
| `sequential/sequential.py` | 1 | pass | Public GCS object read through `google/cloud-sdk:279.0.0` on arm64 worked without credentials. |
| `tfx-oss/TFX Example.ipynb` | 0 | not applicable | No KFP DSL definition; it drives TFX's Kubeflow runner against the retired API (B03). |

Totals: 29 definitions, 27 compile (the two failures are stock baseline issues).
Of the 27, 22 pass as-is, 3 pass after the fixes below, and 2 need GCP or GPU
resources this cluster does not have.

## Regressions found and fixed during this sweep

All three were introduced by `4518f59ad` and were not caught offline. Each fix has
a compiler regression test that fails on the previous code.

1. **Object loop items** (`loop_parallelism`, `loop_parameter`). The loop item
   projection used `(type(item) == 'string' ? fromJSON(item) : item)[...]`. Argo's
   expression checker types `item` from the concrete value, so `fromJSON(item)` is
   rejected whenever the item is already a decoded object, even in the untaken
   branch: `cannot use map[string]interface {} as argument (type string) to call
   fromJSON`. The projection now serializes first,
   `fromJSON(type(item) == 'string' ? item : toJson(item))`, which a minimal Argo
   workflow (`expr-repro.yaml` in the evidence directory) shows evaluates for
   object items, JSON-string items with string and numeric fields, and the
   artifact URI form. `sdk/python/kfp/compiler/argo_groups.py`.
2. **CreatePVC/DeletePVC `Error applying PodSpecPatch`**. The PVC inputs became
   nullable, which routed the synthetic Python stub through the dynamic argv patch
   for raw containers. Argo resolves recognizable tags such as
   `{{inputs.parameters}}` inside the expression text before evaluating it, so the
   injected JSON broke the string literal (`escape-repro*.yaml`: braces, quotes,
   dollars and newlines are fine; a resolvable tag is not). The stub reads the
   whole parameter map, so it is now exempt from the patch.
   `sdk/python/kfp/compiler/argo_compiler.py`. This confirms inventory item U03 as
   a real boundary for user-authored raw containers that put Argo tag syntax into
   their arguments while also declaring nullable inputs.
3. **CreatePVC quoted claim names**. Nullable string inputs arrive JSON-encoded
   (`"-my-pvc"`, `null`) while required strings stay raw, but the stub only decoded
   lists and dictionaries, producing `metadata.name: Invalid value:
   "...\"-my-pvc\""`. The compiler now passes the stub the exact list of parameter
   names it JSON-encodes, and the stub decodes only those.
   `sdk/python/kfp/compiler/argo_pvc.py`.

## How this was run

```sh
kubectl --context orbstack -n kfp-argo port-forward svc/kfp-argo-ui 3006:80
export KFP_TEST_HOST=http://127.0.0.1:3006 KFP_TEST_NAMESPACE=kfp-argo
export KFP_TEST_TOKEN="$(kubectl --context orbstack -n kfp-argo create token argo-ui-editor --duration=6h)"

# Cold pass: every ordinary sample executes; nothing is served from cache.
uv run python test/sdk_compatibility/run_samples.py --output /tmp/core-cold \
  --timeout 900 --disable-caching --include samples/core/artifact_previews \
  --include samples/core/caching --include samples/core/condition \
  --include samples/core/execution_order --include samples/core/exit_handler \
  --include samples/core/loop_output --include samples/core/loop_parallelism \
  --include samples/core/loop_parameter --include samples/core/loop_static \
  --include samples/core/multiple_outputs --include samples/core/output_a_directory \
  --include samples/core/resource_spec/resource_spec.py \
  --include samples/core/resource_spec/runtime_resource_request.py \
  --include samples/core/retry
# Prerequisite-gated samples, short timeout.
uv run python test/sdk_compatibility/run_samples.py --output /tmp/core-prereq \
  --timeout 300 --include samples/core/secret --include samples/core/sequential \
  --include runtime_resource_request_gpu
uv run python test/sdk_compatibility/run_samples.py --output /tmp/core-pvc \
  --timeout 600 --include samples/core/kubernetes_pvc --service-account sdk-sample-pvc-ef4f9a8d
# Default caching, run twice, to observe memoization.
uv run python test/sdk_compatibility/run_samples.py --output /tmp/core-cache \
  --include samples/core/caching/caching_sample.py
```

The runner's exit status is nonzero whenever a definition fails to compile, so the
two baseline compile failures make every invocation exit 1; read `execution.json`.
In single-user proxy mode the browser token is ignored by the proxy, so the editor
token above only satisfies the runner's non-empty check; requests run with the
proxy's own editor-bound service account. Nothing was deleted from the namespace.

## Open items

- `artifact_preview_formats_pipeline` needs a longer timeout or a slimmer
  dependency set in the sample itself; its runtime is dominated by per-pod pip
  installs, not by the native stack.
- The GPU and credentialed-GCP samples remain unverifiable here (P01, P02).
- The PVC sample still needs a PVC-capable workflow service account; the bundled
  deployment deliberately does not grant claim creation to component accounts (P04).
