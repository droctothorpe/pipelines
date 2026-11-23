# Backwards-compatibility inventory

**Snapshot: 2026-11-20. Implementation is paused for inventory and commit.**

Reference: stock KFP commit `7780f12acfbde9f16169c7fcbfdfb6c3ef5432ea`.
This document covers all confirmed differences and unresolved compatibility areas
identified during the native-Argo migration. It supersedes the earlier working
inventory. It is **not a certification that everything absent from this list is
compatible**, nor a claim that every possible SDK argument combination was tested.
The intended contract and detailed implementation evidence are in
[SDK compatibility](sdk-compatibility.md).

## How to read this inventory

- **A — Accepted departure:** a known difference explicitly accepted for this work.
- **C — Confirmed gap:** user-facing functionality is missing, rejected, or narrower
  in the current implementation. Unless marked A, it is not an approved removal.
- **L — Known limit, uncertain stock impact:** the current boundary is established,
  but a stock-valid counterexample or exact stock equivalence is not established.
- **U — Uncertain:** implemented but insufficiently verified, an unresolved failure,
  or an area whose stock/native behavior has not been fully compared.
- **P — Prerequisite:** unavailable hardware, credentials, or installation coverage.
- **B — Baseline issue:** stock itself fails, or stock support has not been established.

A passing signature, unit test, compilation, terminal workflow phase, or mocked
browser test is not by itself proof of end-to-end compatibility. Earlier live
passes do not prove that every subsequent compiler/runtime change works live.
No C/L/U entry should be called an inherent Argo limitation without further evidence.

## Verification checkpoint and remaining closeout

| Evidence | What it establishes | What it does not establish |
|---|---|---|
| 65 frozen signatures plus the top-level Client alias check | Captured calling conventions are restored | All methods' behavior, exceptions, fields or external integrations |
| Full retained Python suites: **1,338 passed, 2 xfailed, 302 subtests**, on Python 3.11 and 3.13 | Current retained offline SDK/compiler/client tests pass | Execution of every generated workflow or every stock SDK feature |
| Frontend CI: **295 unit tests**, offline viewer smoke and **3 production-bundle browser tests** | Build, retained UI logic, mocked API workflows and offline viewer pass | Current deployment parity, full visual equivalence or live authorization for recent changes |
| **27/29** captured stock definitions compile with both SDKs; all 27 native manifests pass offline Argo lint | No remaining compilation failure in the stock-compilable corpus | Every original notebook cell, full-sized input, runtime branch or dependency environment |
| **25/27** stock-compilable definitions passed live across earlier retained reports | Substantial real execution coverage | A complete live pass of the code being committed; GPU/cloud cases remain |
| Latest live corpus rerun: **8 cases passed**, then transport failures; unchanged PVC sample separately passed | Partial rerun evidence | Remaining cases were not verified; preview-formats timed out before the later API outage |
| Wheel/sdist builds and isolated installed-wheel smoke | Packaging includes tested native modules and bindings | Every installation platform, dependency resolution or external registry |

The local Kubernetes and Docker APIs became unavailable during validation. The
most recent Kubernetes `/readyz` check returned `ok`, **but the interrupted tests
have not been resumed**. That health response does not verify Docker, Argo Server,
SQL reconnection, the UI port-forward or any pending live case. The last deployed
UI image was `kfp-argo-ui:compatibility-20261120-080712`; newer changes are in the
checkout/build, not that deployment. No restart or data deletion was used to
resolve the outage.

Remaining closeout is a live rerun, investigation of its failures, completion of
the C entries if full parity is still required, and resolution of the U/L/P items.
This commit is an explicit compatibility checkpoint, not a declaration of completion.

## A. Accepted departures

| ID | Surface | Known difference / agreement |
|---|---|---|
| A01 | Compiled execution format | Native WorkflowTemplate/Workflow/CronWorkflow replaces PipelineSpec execution IR and KFP PipelineVersion CRDs. Historical IR manipulation/import is outside the agreed target; recompile original Python. Portable container component definitions remain supported. The UI package importer accepts the labelled native WorkflowTemplate document the compiler emits; the SDK client is the full authoring path (YAML/JSON/zip/tar and every resource kind), and URL import is subject to browser CORS because the Node server that proxied it is retired (formerly C21, folded in 2026-11-23). |
| A02 | Backend and wire protocols | KFP backend/controllers, old REST/gRPC service transports and per-component driver infrastructure remain removed. Public SDK/UI outcomes are the target, not the old internal endpoints or storage layout. |
| A03 | Local execution | Local runners/local execution remain removed. Passing `execute_locally=True` does not restore them. |
| A04 | Missed recurring occurrences | Native Argo recovers at most one missed occurrence within its recovery window, not every missed occurrence. No backfill dispatcher. |
| A05 | Artifact-list staging architecture | A consumer init-container may stage runtime-sized collections using the installed Argo downloader. No additional copy pods; storage credentials remain init-only. This is an accepted implementation mechanism, not permission to drop artifact behavior. |
| A06 | System Logs tab | The obsolete KFP System Logs tab was removed at the user's request. Task logs, details and I/O remain. |
| A07 | Release infrastructure | The old release/merge-queue machinery was retired with approval. Native CI/security/contributor checks are not a replica of the retired release system. |
| A09 | Response fields owned by the retired backend | Accepted 2026-11-20. These stock response fields stay unset because their source no longer exists; they are not fabricated. `V2Run`: `error`, `plugins_input`, `plugins_output`, `run_details` (MLMD context ids). `V2RecurringRun`: `error`, `plugins_input`. `V2Pipeline`/`V2PipelineVersion`: `error`, `tags`, `package_url`. `V2Artifact`: `description`, `number_value` (MLMD custom properties). `PipelineTaskTypeAttributes.download_to_workspace` (C07). Pod `uid` after the pod is garbage-collected or for archived runs. Formerly C19 and U49–U54; the fields Argo can supply are populated, see the field table. |
| A08 | Artifacts page scope | Accepted 2026-11-20. The Artifacts page lists artifacts from the latest 50 runs and shows a truncation notice; it is not a global artifact catalog or index. Artifacts remain reachable through their runs, which is where they are used. Maintaining an index would add state the native stack otherwise avoids, for a page that is rarely the entry point. Formerly C22. |
| A10 | Workspace access-mode default | Accepted 2026-11-21. A workspace must declare `accessModes` in `pvcSpecPatch`. Stock behaves the same by default: `argocompiler.GetWorkspacePVC` rejects a claim without access modes unless the API server was given a `workspace.volumeclaimtemplatespec` block, which the stock manifests do not ship and which must itself carry access modes and a storage class. Only that opt-in admin knob is lost, and there is no server here to hold it. Pipelines that relied on it add the access modes to the pipeline. |
| A11 | Stock data migration | Accepted 2026-11-21. No tooling migrates an existing stock KFP run database, metadata history or stored pipeline catalog into the native stack, and no complete namespace export/import path is supplied. The native stack keeps run history in Argo and its archive and pipelines as WorkflowTemplates; stock history stays readable in the stock deployment it came from. Recompile original Python to bring pipelines across. |
| A12 | Launcher debug pause | Accepted 2026-11-21. Stock's launcher-owned before/after/error pause hooks (added to master on 2026-11-06, #14492) have no counterpart: there is no launcher, and Argo's suspend/resume is a workflow-level operation, not an in-container breakpoint. |
| A13 | Run plugin inputs | Accepted 2026-11-21. `plugins_input` on run creation (API field from the 2026-06-01 MLflow merge, SDK argument from 2026-10-30, #14114) feeds API-server plugins that do not exist here. The native client raises rather than dropping the inputs silently. |
| A14 | OCI modelcar imports and repository plugins | Accepted 2026-11-23. Native pipelines store and import artifacts through S3/GCS repositories, plus HTTP(S) for importers and list staging. Stock's `oci://` importer (#11606, 2025-02-19) prepulled a Modelcar image in an init container and ran it as a sidecar managed by the launcher, which no longer exists, and Argo has no OCI artifact driver. The native importer rejects `oci://` with an explicit error rather than failing at runtime, and automatic previews already skip OCI outputs. Argo repository plugins cannot serve pipelines because runs bind to a bucket (C14); staging names that limit explicitly. Other stock provider/integration combinations are not substitutes for these supported paths. Formerly C13. |
| A15 | Managed TensorBoard viewers | Accepted 2026-11-23. Stock's `tensorboard` entry in a legacy `mlpipeline-ui-metadata` artifact asked the frontend server to create a Viewer custom resource, and the viewer controller launched a TensorBoard pod behind a proxy; both are retired and are not replaced. The native UI shows the entry with its log directory for use in an external TensorBoard. Formerly part of C23. |
| A16 | Experiment archival atomicity | Accepted 2026-11-23. Stock archived an experiment and its runs in one database transaction. Native archival is an ordered, retryable sequence of Argo and Kubernetes mutations with the failing step reported; a partially archived experiment is visible as such and the operation is repeated to completion. No transaction exists without a database, and a fencing controller is out of scope. Concurrent run or schedule creation during archival is the same race stock had at its API boundary. Formerly C20. |
| A17 | Literal parameter choices | Accepted 2026-11-23. Upstream's UI rendered a required dropdown for pipeline inputs declaring `literals` in the IR. No Python SDK release emits that field, so only hand-written IR and upstream's own integration fixtures ever produced it. The native run form renders a typed free-text field. Formerly C29. |

## C. Confirmed gaps or narrower functionality

### Authoring, runtime, artifacts and Kubernetes

| ID | Surface | Current difference | Evidence / boundary |
|---|---|---|---|
| C01 | Nested graph task retry | **Resolved 2026-11-20 as parity.** A retry policy on a nested pipeline task now compiles with a warning and is not applied, which is what stock does: its Argo compiler neutralizes DAG retries because retrying a DAG re-runs the whole subgraph. Inner task retries are unaffected. | `compiler/argo_compiler.py:compile_component`; `argo_compiler_test.py` |
| C02 | Nested graph custom caching | **Resolved 2026-11-20, beyond stock.** A custom cache key on a nested task scopes every inner task's cache identity (stock records the key but never applies it). Disabling caching on a nested task already propagated. Pipelines without nested keys keep their existing fingerprints. Verified live: same key cached, new key executed. | `argo_compiler.py:leaf`; `argo_compiler_test.py` |
| C03 | Nested graph platform overrides | **Resolved 2026-11-20, beyond stock.** Static kfp-kubernetes settings on a nested task reach every inner pod (stock drops them): dictionaries merge, lists accumulate, the inner task wins on conflicts. Settings bound to pipeline parameters or task outputs are rejected with a message naming the task, since inner tasks cannot resolve them. Verified live: a secret env and node selector set on the nested task appeared in the inner pod. | `argo_compiler.py:_kubernetes_config`; `argo_compiler_test.py` |
| C04 | Cross-boundary failure-tolerant inputs | **Resolved 2026-11-20.** A failure-tolerant consumer inside a condition, loop or nested group may now consume a producer outside the group. The group item tolerates the producer's failure, forwards a guarded value and a `kfp-present-<port>` flag through every template on the way down (loop fan-out wrappers included), and the consumer applies its own fallback. Verified live: with a failing producer the run ends FAILED while the consumer in a condition, a two-iteration loop and a nested condition succeeded with its default; with a succeeding producer it received the value. Remaining limit L16. | `compiler/argo_continuation.py:arguments`, `argo_groups.py:thread_presence`; `argo_compiler_test.py` |
| C05 | Raw-container failure-tolerant inputs | **Resolved 2026-11-20.** A raw container may consume a producer it tolerates failing without an explicit default: the `kfp-present-<input>` flag becomes the IfPresent condition in its argv, and a nullable input receives the literal `null` after the failure. Verified live: with a failed producer the container took the else branch (`--absent`), with a successful one it received the value. | `compiler/argo_compiler.py:leaf`, `argo_continuation.py:arguments`; `argo_compiler_test.py`, `test/e2e/test_container_optional_inputs.py` |
| C06 | Workspace deployment defaults | Moved to accepted departure A10 on 2026-11-21. | `compiler/argo_workspace.py:configure` |
| C07 | Importer download to workspace | **Resolved 2026-11-20.** `download_to_workspace=True` wraps the podless importer in a template that resolves the artifact and then runs a download step copying the payload to the path `dsl.Artifact.path` derives for workspace-resident artifacts (`/kfp-workspace/.artifacts/<scheme>/...`, `gs://` under `gcs/`), and marks the artifact `_kfp_workspace` as stock does. Consumers in the same graph read it from the shared volume without staging a second copy; consumers in another graph receive a staged copy and the flag is dropped for them. Requires `PipelineConfig(workspace=...)`; a run cached at the resolve step still downloads, since the workspace is per run. Verified live: the download pod and the consumer were the only pods mounting the workspace and the consumer read the payload at the expected path. | `compiler/argo_importer.py:_with_download`, `argo_compiler.py:workspace_import`, `dsl/argo_runtime.py:execute`; `argo_compiler_test.py`, `test/e2e/test_importer.py` |
| C08 | Workspace TaskConfig in raw containers | **Closed 2026-11-20: no stock difference.** TaskConfig passthroughs are declared by `@dsl.component` and notebook components only; `@dsl.container_component` has no `task_config_passthroughs` in stock or here, so no Python-authored raw container can receive a workspace passthrough. The guard stays for hand-written component YAML. | `dsl/component_factory.py`, stock `sdk/python/kfp/dsl/container_component_decorator.py` |
| C09 | Dynamic structured TaskConfig in raw containers | **Closed 2026-11-20: no stock difference.** Same reasoning as C08: dynamic structured projection reaches a component only through passthroughs, which raw containers cannot declare from Python in either tree. | `compiler/argo_structured.py:finalize` keeps the YAML guard |
| C10 | Mixed dynamic affinity | **Resolved 2026-11-20.** A static term and a JSON term bound to a pipeline parameter merge the way stock's driver appends them: static node selector terms and preferences first, then the resolved JSON's, with a null value adding nothing and an empty required list omitted. Verified live: a static required term and a dynamic preferred term both reached the pod. | `compiler/argo_kubernetes.py:lower`, `argo_structured.py:_merge`; `argo_structured_test.py`, `test/e2e/test_kubernetes_settings.py` |
| C11 | Mixed dynamic resource claims | **Resolved 2026-11-20** in the compiler by the same merge: static claims and their container references first, then each resolved JSON declaration. The cluster used for verification has no DRA driver, so the merged pod patch is verified by compiled output only. | `compiler/argo_kubernetes.py:lower`; `argo_structured_test.py` |
| C12 | Entrypoint-only raw artifact-list consumers | **Closed 2026-11-20: no stock difference.** Stock's launcher runs `cmdArgs[0]` as the executable and rejects an empty command and argument list, so an image-entrypoint-only container does not run on stock either. Outside list staging the native pod honors the image entrypoint, which stock cannot. | stock `backend/src/v2/component/launcher_v2.go:128,137`; `compiler/argo_artifact_lists.py:add_staging` |
| C13 | Storage/provider coverage | Moved to accepted departure A14 on 2026-11-23. | `argo_importer.py`, `client/_artifact_repository.py` |
| C14 | Stock default storage policy | **Resolved 2026-11-23.** Compiled artifacts carry keys only and `Compiler()` bakes no root. When a run is submitted, the client or UI reads the namespace's Argo `artifact-repositories` ConfigMap (annotated default entry, else the controller default where readable) and binds its bucket into the run, which is stock's per-namespace `kfp-launcher` policy expressed through Argo's own repository chain. An explicit `pipeline_root` selects the entry serving its bucket with `artifactRepositoryRef`; a bucket no entry serves is refused with a 400 before anything is created. The runtime compares the bound bucket with the repository Argo staged for the pod and fails loudly on a mismatch. Verified live: `test/e2e/test_pipeline_root.py` (default and explicit roots) and the multi-user tenant with its own bucket in `test_multi_user.py`. Foreign buckets without a repository entry are L18. | `compiler/argo_artifacts.py:bind_root`, `client/_artifact_repository.py`, `frontend/src/lib/NativeArtifacts.ts`, `dsl/argo_runtime.py:check_archive_location` |
| C15 | Non-Kubernetes platform extensions | **Resolved 2026-11-20 to stock behavior.** Stock's backend applies only the `kubernetes` platform spec and carries any other platform's settings unexecuted; the native compiler now warns and ignores them instead of rejecting the pipeline. | `argo_compiler.py:_kubernetes_config`; stock `backend/src/apiserver/template/v2_template.go:136`; `argo_compiler_test.py` |
| C16 | Launcher debugging barriers | Moved to accepted departure A12 on 2026-11-21. | Native bootstrap/runtime replaces the launcher |

### SDK, lifecycle, UI and integrations

| ID | Surface | Current difference | Evidence / boundary |
|---|---|---|---|
| C17 | Backend plugin inputs | Moved to accepted departure A13 on 2026-11-21. | `client/_native.py:_workflow_spec` |
| C18 | Certificate-only full history/artifacts | **Resolved 2026-11-23.** A client authenticating directly against Kubernetes (`kube_context`, in-cluster credentials) sends engine-only routes, meaning the archive, to Argo Server itself with the same Kubernetes token, which Argo Server's client auth mode accepts; everything else goes to the Kubernetes API. The address comes from `Client(argo_server=...)`, else the Argo CLI's `ARGO_SERVER`/`ARGO_SECURE`/`ARGO_BASE_HREF`, else the `argo-server` Service in the client's namespace inside a cluster; `ARGO_INSECURE_SKIP_VERIFY` disables its TLS check and `ARGO_TOKEN` supplies a token for certificate-only kubeconfigs. The UI proxy is no longer on the SDK path. Without any address outside a cluster, listings still warn once and cover live runs. Evidence: `test/native_transport_test.py` (red without the route), live `test/e2e/test_kube_context.py` (2 passed against OrbStack with a deleted live workflow read back from the archive), both in CI with `KFP_TEST_CONTEXT`/`KFP_TEST_ARGO_SERVER`. | `client/_transport.py`, `client/client.py:_argo_server_endpoint` |
| C19 | Historical task/MLMD detail | **Resolved 2026-11-20** for everything Argo can supply: task and run state history, scope path, iteration attributes, lifecycle category and stock's lifecycle-message normalization, pod UIDs while pods exist, artifact creation times and input producers, experiment last-run time, schedule update time and run scheduled time. The remainder is accepted as A09. | `client/_task_details.py`, `client/_native.py`, `test/native_task_details_test.py`, `test/native_client_test.py`; field table below |
| C20 | Atomic experiment archival | Moved to accepted departure A16 on 2026-11-23. | `_native.py:_experiment_storage`, `NativeUi.ts:setExperimentStorage` |
| C21 | UI package upload breadth | Folded into accepted departure A01 on 2026-11-23. | `frontend/src/lib/NativeImport.ts`, `pages/NativeUpload.tsx` |
| C22 | Artifact discovery breadth | Moved to accepted departure A08 on 2026-11-20. | `frontend/src/lib/NativeQueries.ts:useArtifactInventory` |
| C23 | Legacy visualizations | **Resolved 2026-11-23** for the viewer routing: an output artifact whose name normalizes to `mlpipeline-ui-metadata` is read through Argo Server and its `outputs` entries render with the kept viewers (`table`, `confusion_matrix`, `roc`, `markdown`, `web-app`), as stock v2 does; `web-app` uses stock's `allow-scripts` iframe sandbox like typed HTML artifacts (C24). Sources are inline text or the URI of one of the producing task's own output artifacts (L19). TensorBoard is accepted departure A15. Evidence: `NativeUiMetadata.test.ts`, `NativeInspectors.test.tsx`, live `test/e2e/test_visualizations.py::legacy-ui-metadata` and `frontend/e2e/legacy-visualizations.test.mjs` (1 of 1 passed against OrbStack `kfp-argo`). | `lib/NativeUiMetadata.ts`, `viewers/NativeUiMetadata.tsx` |
| C24 | Markdown/security rendering | **Resolved 2026-11-23 as stock parity.** The Markdown viewer is the stock component (raw HTML disabled, the parser's own URL sanitizer, remote images fetched as written) plus scoped document styles; HTML artifacts and legacy `web-app` viewers use stock's `sandbox="allow-scripts"` iframe. The fork's earlier extra restrictions (http-only links, inline-image-only, script-free CSP sandbox) were removed so behavior matches stock exactly; the hardening is proposed upstream in [kubeflow/pipelines#15903](https://github.com/kubeflow/pipelines/issues/15903). Evidence: `NativeInspectors.test.tsx` (javascript: link dropped by the sanitizer, remote `img` kept, `allow-scripts` sandbox with verbatim `srcdoc`), live `frontend/e2e/markdown.test.mjs` (remote image requested, no script execution in the page) and `frontend/e2e/legacy-visualizations.test.mjs` (web-app script runs inside its frame, UI title untouched). | `components/viewers/MarkdownViewer.tsx`, `viewers/NativeUiMetadata.tsx` |
| C25 | UI log breadth | **Resolved 2026-11-20.** Running tasks stream live from their pod with `follow` and no tail limit; finished tasks load the complete archived `main-logs` artifact, which also serves runs whose workflow object or pod is gone; a finished task with nothing archived falls back to the full pod log while the pod exists. Verified in the browser against the OrbStack namespace: live lines grew without refresh and ended at 365 lines, the finished task read 361 archived lines, and a deleted run read its archive. Not restored: stock's per-container selection and log search. | `frontend/src/lib/NativeUi.ts:streamTaskLogs`, `NativeRunDetails.tsx:useTaskLogs`, `NativeUi.test.ts`, `native-bundle.smoke.mjs` |
| C26 | Migration and export/import | Moved to accepted departure A11 on 2026-11-21. | Native architecture and deployment scope |
| C28 | Explicit ordering across group boundaries | **Resolved 2026-11-20.** A task inside a condition, loop or nested group may call `.after()` on a task outside the group. The dependency is lifted onto the group item in the scope that owns the target, as stock lifts it onto the enclosing group; a failure-tolerant depender relaxes that dependency, and its `PipelineTaskFinalStatus` input receives the target's status through a `kfp-after-<task>` flag threaded like the C04 presence flags. Verified live: an inner task started only after the outer task finished and was omitted when it failed; a tolerant reporter inside a loop inside a condition saw FAILED and SUCCEEDED correctly. Mixed tolerance is rejected (L16). | `compiler/argo_groups.py:lift_after`, `argo_continuation.py:dependencies`; `argo_compiler_test.py`; `test/e2e/test_ignore_failure.py` |
| C29 | Literal parameter choices | Moved to accepted departure A17 on 2026-11-23. | `frontend/src/pages/NativeForms.tsx`, `NativeParameterInput.tsx` |
| C27 | Kubeflow integration/session UX | **Resolved 2026-11-21.** `deploy.py --auth-mode multi-user` is the Kubeflow platform mode: cluster-wide Argo, a proxy that trusts the gateway's `kubeflow-userid` header (name and prefix configurable, as stock) and runs a SubjectAccessReview for that user on every proxied request before acting with its own account; aggregated `kfp-native-edit`/`kfp-native-view` ClusterRoles for Kubeflow namespace members; `--tenant` for per-namespace resources; `--istio-gateway` for the `/pipeline` VirtualService and ingress-only AuthorizationPolicy. The UI serves under `/pipeline/`, follows the central dashboard's namespace protocol and hides its own navigation when embedded. SSO itself is the platform's oauth2-proxy/Dex, as in stock. Verified live: `test/e2e/test_multi_user.py` (4 passed) and `frontend/e2e/multi-user.test.mjs` against a tenant namespace; CI runs both in `test/native-deployment.sh`. Tenant onboarding is a manifest, not a profile-controller hook (L17). | `samples/argo-native/ui-proxy.js`, `deploy.py`, `frontend/src/lib/Dashboard.ts` |

## L. Confirmed implementation limits with uncertain stock impact

These are **category (b)** until stock-valid counterexamples or exact equivalence
are established. Do not call all validation errors regressions.

| ID | Boundary | Established limit and unresolved comparison |
|---|---|---|
| L01 | Fractional retry factors | Positive integral factors, including integral floats, work; fractional factors are rejected. Stock's compiler forwarded a float string, but the stock/pinned Argo runtime uses an integer factor. Exact stock execution semantics are not established; the signature alone is insufficient. |
| L02 | Root artifact inputs | Native root artifact binding is rejected. Stock RootDAG/runtime configuration evidence exposes parameters, not an established public artifact-root submission path. Nested artifact inputs work. See B04. |
| L03 | Remaining graph escape/aggregation guards | Direct conditional-output escape, uncollected loop outputs, unmapped artifact aggregation and unsupported dependency scopes still have guards. Some are invalid in stock too; valid OneOf/Collected cases must be distinguished from unsupported combinations. |
| L04 | Workspace storage-class validation | Empty `storageClassName` is rejected; prior stock-source investigation also found rejection. Do not report this as a migration regression without a valid baseline. |
| L05 | Package size/shape | SDK packages are limited to 64 MiB uncompressed, exactly one supported native manifest, with embedded templates/entrypoint. Reference-only or multi-document native bundles are not accepted. Historical IR is separately A01. |
| L06 | Raw argument and collection size | Raw staged arguments at or above 128 KiB are rejected; the process argument limit also constrains stock executables. Python list consumers use files instead. Collection flattening has a 64-level nesting guard. |
| L07 | Compressed node status | Local gzip status expansion is limited to 64 MiB. Malformed/oversized gzip fails explicitly. Alternative codecs or SQL-only status need server hydration; unavailable inventory returns None. |
| L08 | Preview size | Dataset/Model preview retrieval is bounded to 64 KiB and does not fetch arbitrary full payloads. Oversized/legacy previews need comparison with stock. Markdown retains the stock 400,000-character cap; that cap is not a newly established regression. |
| L09 | URI validation | Staging rejects credential-bearing URIs, fragments, and object-storage query strings. HTTP(S) does not inherit repository storage credentials. Legitimate stock inputs outside these rules need explicit comparison, not silent credential forwarding. |
| L10 | Changing artifact roots | Packages without compiler-owned root bindings must be recompiled. Switching schemes while explicit driver credentials/settings are attached is rejected. Normal immutable-version root overrides are implemented. |
| L11 | Old cached identities | A cached identity without inline metadata, a metadata companion URI, or a derivable canonical metadata path cannot be reconstructed; the stager requests producer regeneration. This is not migration of arbitrary stock MLMD records. |
| L12 | Executor command recognition | The portable bridge requires a recognized SDK executor invocation. Arbitrary wrappers, alternate entrypoints and flag collisions need testing. |
| L13 | Artifact path/layout assumptions | Native local paths, IDs and storage layout differ from old backend implementation details. Payload access and origin are preserved in tested cases; user code hard-coding launcher paths/MLMD IDs is not established as compatible. |
| L14 | Resource-size ceilings | Native ConfigMap caches/registries and Workflow/annotation limits remain. Cache sharding/eviction and large-root-parameter handling are not proven. In particular, duplicating runtime parameters into annotations may hit the annotation limit before the workflow limit; this is an untested risk, not a reproduced stock regression. |
| L16 | Mixed tolerance inside a group | When a group contains both a failure-tolerant and an ordinary consumer of the same outside producer, or both a tolerant and an ordinary `.after()` on the same outside task, compilation is rejected with a message naming the output and group, because the group as a whole must either wait for the producer to succeed or tolerate its failure. Stock evaluates each task individually. Make every consumer in the group failure-tolerant, or move the ordinary consumer out. |
| L15 | Individual UI run archival | The UI's individual-run archive helper allows only terminal runs, while SDK archival and experiment cascading can archive active runs without termination. Exact stock UI selection/guard behavior still needs comparison. |
| L17 | Tenant onboarding | Stock's metacontroller sync creates per-profile pipeline resources automatically. The native stack prepares a namespace with `deploy.py --tenant NAME` (workflow account, cache, template-offload rights, artifact repository and credentials). Namespaces that skip it cannot run pipelines until it is applied; the Kubeflow profile controller still provides people's bindings. | `samples/argo-native/deploy.py:tenant_resources` |
| L18 | Buckets outside the namespace repositories | A `pipeline_root`, and an importer or artifact-list URI, must name a bucket that one of the namespace's `artifact-repositories` entries serves, since Argo takes endpoint and credentials from that entry. Stock reached the same place through the `kfp-launcher` providers table. Add an entry per bucket; the submitter selects it by bucket. Importer URIs in unserved buckets fail at download rather than at submit. | `compiler/argo_artifacts.py:bind_root`, `argo_importer.py` |
| L19 | Legacy viewer sources | A legacy `mlpipeline-ui-metadata` entry's `source` must be `inline` or the URI of an output artifact of the same task, which Argo Server serves. Stock's Node server read any object in the bucket, so entries pointing at other locations (including other tasks' artifacts) show an error instead of the viewer; write the data as a sibling output artifact and reference its `.uri`. |

## U. Compatibility not established

### Compiler, runtime, storage and configuration

| ID | Area | What remains uncertain | Existing coverage / next evidence |
|---|---|---|---|
| U01 | Artifact-list iteration | Latest single-item staging and nested list iteration have not run live. | Compiler/stager/runtime tests and native lint pass; `test/e2e/test_artifact_lists.py` iteration cases remains unrun. |
| U02 | Nullable raw-container argv | None/empty/literal-null handling, nested Concat and staged-list IfPresent need actual execution. | BusyBox fixture `test/e2e/test_container_optional_inputs.py`; 25 temporary pinned Expr/Sprig evaluations are only expression-level evidence. |
| U03 | Literal native-template text | Strings such as `{{inputs.parameters.value}}` or `{{workflow.uid}}` must remain data where stock does. Argo performs multiple substitution passes. | Confirmed live 2026-11-20: Argo resolves a recognizable tag inside a `{{=...}}` expression string literal before evaluation, breaking the dynamic argv patch for raw containers with nullable inputs; brace escaping alone does not protect it. The compiler-generated PVC stub is now exempt ([core samples](core-samples.md)); user-authored raw containers that embed Argo tag text and declare nullable inputs remain an open boundary. |
| U04 | Nullable Kubernetes settings | Nullable source channels in resource quantities, env, resource names and structured settings have not been fully lowered/verified. | Non-null dynamic settings and Python nullable parameters passed separately. |
| U05 | Whole control-flow combination space | Nested loops/conditions/OneOf, zero iterations, conditional/skipped producers, collection returns, explicit dependencies and their combinations are not exhaustive. | Many retained cases pass; remaining guards are C04/C05/L03, not proof that every other combination works. |
| U06 | Retry/failure combinations | Retries with validation wrappers, cleanup, caching, lists, workspaces, nested graphs and cancellation need broader live coverage. | Default/integral retry samples and targeted failure cleanup passed; latest nested task/pod projection is unit-tested. |
| U07 | Raw scalar validation edges | Malformed float/dict, valid JSON of the wrong shape, overflow/nonfinite values, optional outputs and all retry/cache combinations are not fully live-tested. | Valid scalar types and malformed integer/bool/list runs were tested. |
| U08 | Artifact list error/provider matrix | Metadata mismatch, download interruption, credentials expiry, provider changes, consumer cache hits, cross-root references and historical identity variants need broader validation. | Cached files/directories, empty/nested collections, missing-object failure, HTTPS and 256-item consumption passed in selected cases. |
| U09 | Stager execution layouts | Init-less/alternative Argo executors, binary paths, images/architectures and externally customized pod patches are not verified. | Pinned regular Argo 4.1.6 layout was tested. |
| U10 | Artifact-list schedules | SDK periodic execution passed; every UI-created recurring staging path, trigger and rebind combination is not established live. | Shared SDK/UI binding code and unit tests are not all schedule execution paths. |
| U11 | Importer variants | Complete HTTP/GCS/provider semantics, dynamic metadata shapes, reimport/cache concurrency and all artifact types remain unverified. | S3 and selected HTTP consumption passed; workspace materialization is C07. |
| U12 | Workspace lifecycle matrix | Access modes/storage classes, concurrent tasks, failed/cancelled runs, cleanup races, imported paths and custom cache keys need further testing. | Explicit-spec shared files, dynamic paths, unrelated-task caching and successful owned-claim cleanup passed. |
| U13 | TaskConfig matrix | Every field combination, nested scope, apply-to-task mode and older SDK runtime combination is not verified. | Selected CPU/env/selectors, external-only workspace/DRA projection passed; C06 and C08–C11 are closed. |
| U14 | Kubernetes modifier breadth | All schema fields, scheduling constraints, security contexts, volume conflicts and dynamic/static combinations have not been compared. Unmapped fields still reject. | Retained pod-shape/live settings tests cover a subset; this is not every Kubernetes plugin configuration. |
| U15 | DRA execution | Correct Pod claim fields and external-only projection do not prove device allocation/use/release. | Shape tests only; the owned shape-test workflow was terminated. See P01. |
| U16 | Runtime image/SDK breadth | Other SDK versions, Python versions in user images, containerized components, custom executor wrappers, offline/restricted installation and image authentication need coverage. | Default images and unmodified PyPI KFP 2.17.0 passed selected cases; local test suites cover Python 3.11/3.13. |
| U17 | Less-exercised authoring APIs | Notebook components, externally loaded/containerized definitions, custom artifact subclasses, output/default/type combinations and less-common valid placeholders lack a complete runtime matrix. | Restored authoring unit tests and the stock corpus are substantial but not exhaustive. |
| U18 | Caching under real load | Concurrent identical tasks, cache write conflicts, capacity exhaustion, eviction, stale mutable dependencies and all overrides are not proven. | Default-on, custom-key, pipeline scope, cold/hot runs and cached artifact identity passed selected tests. |
| U19 | Root/storage combinations | GCS credentials, mixed providers, root changes with explicit driver settings, custom artifact URIs and provider-specific metadata need further execution. | S3 payload/URI/root overrides passed; provider limits are C13/L09/L10. |
| U20 | File/directory edge semantics | Symlinks, modes, unusual filenames, large files, custom paths, direct artifact executables and archive formats have not been exhaustively compared. | Ordinary files/directories and payload checks passed. |
| U21 | Preview variants | Manual v1-directory previews, full format/type coverage after latest changes, oversized/absent/corrupt previews and all classification variants are not fully live-verified. | Sibling v2 Dataset/Model previews, ROC/confusion and selected Markdown cases passed earlier. |

### SDK, authentication, lifecycle and scheduling

| ID | Area | What remains uncertain | Existing coverage / next evidence |
|---|---|---|---|
| U22 | Latest experiment cascade | SDK/UI archival, partial failure/retry, late-created runs and parent-first restoration need live verification. | Unit and mocked production browser tests pass; `test/e2e/test_experiment_archive.py` is retained but unrun. |
| U23 | Compact inventory API behavior | Latest field projection, metadata-only negotiation, count-aware paging, cache lag and identity reconciliation need live verification on the deployment. | Upstream source, unit and mocked browser tests pass; read-only `test/e2e/test_inventory.py` is unrun. |
| U24 | Latest task projection | Gzip snapshots and nested retry/validation pod ownership need live proof, especially compressed/offloaded histories and retries. | New red/green tests pass; prior typed task snapshots were checked live before these edits. |
| U25 | Complete response/exception parity | Full DTO field availability, error codes/categories, I/O producer classification, child hierarchy, cancellation state and serialization equivalence remain incomplete. | The field parity table below records what is populated and A09 what is accepted as absent; whole-response and exception equivalence per operation is still uncompared. |
| U26 | Filtering and pagination semantics | All filter operators/field aliases/types, empty inventories, ordering ties, paging under mutation and old cursor/error expectations lack complete baseline comparison. | `_listing.py` has retained tests; old wire tokens are not preserved. |
| U27 | Remaining lifecycle edges | Default-experiment deletion protection, orphan membership, deletion races, already-deleted resources, default/shared version selection, unregistered template adoption and all clone paths need review. | Basic CRUD/UID/name-reuse tests pass. No new destructive probes were run to close these questions. |
| U28 | Recurring trigger semantics | Seconds-bearing cron, time zones/DST, start/end boundaries, outage windows, concurrency saturation/queued-vs-skipped occurrences and enable/disable races need full comparison. | Periodic/default-enabled/cron configuration and selected executions passed. Six-field zero-seconds normalization is narrower than arbitrary seconds cron. A04 only accepts missed-occurrence catch-up, not every other scheduling difference. |
| U29 | Authentication matrix | SSO/IAP/OIDC/Dex/cookies, proxy/TLS variants, token expiry/refresh under live load, impersonation expectations, in-cluster deployments and archive-path credentials are not all proven. | Certificate and SA direct Kubernetes execution, reader denial, and offline credential tests passed; multi-user header identity with per-request SubjectAccessReview passed live (C27). C18 remains. |
| U30 | Registry interoperability | Remote registry upload/download/auth/version behavior for native packages is not live-established. | Public entrypoints and restored registry unit tests pass, not a production registry integration. |
| U31 | CLI and notebook helpers | All command flags, output/error text, context/config/completion behavior, diagnostics and notebook links/widgets need full stock comparison. | Groups/aliases and exact-source loading regressions pass; old backend diagnostics may not describe the native topology fully. |
| U32 | Long-lived SDK clients | Refresh/retry/reconnection, multiple namespaces, concurrent operations and route caches under sustained churn need broader live coverage. | Warm route lookup remains fresh and UID-safe; cold metadata-only lookup is currently offline-tested. |
| U33 | Package and upload matrix | All archive layouts, malformed packages, external URLs/CORS, remote component packages and storage policies lack exhaustive compatibility checks. | Bounded safe extraction-free loading is tested; C21/L05 are explicit boundaries. |

### UI and operations

| ID | Area | What remains uncertain | Existing coverage / next evidence |
|---|---|---|---|
| U34 | Full visual parity | Every stock page, dialog, populated state, error state, viewport, browser and accessibility interaction has not been compared. | Five empty list pages were compared earlier; later targeted screenshots are not whole-UI pixel parity. |
| U35 | Remaining UI actions | All selection, bulk actions, nested expansions, comparisons, uploads, clone/restore/delete flows and deep-link states need final audit. | Recent experiment layouts/default tabs/refresh and nested links have targeted tests, not a complete UI action inventory certification. |
| U36 | Artifact comparisons/lineage | Rich cross-run artifact comparisons and complete lineage navigation/catalog behavior are not established. | Basic typed artifacts, origin, previews and classification rendering passed selected cases. C23 remains; the 50-run artifact list scope is accepted as A08. |
| U37 | Logs/history/downloads (task log streaming and archive fallback are now covered by C25) | Long/streaming/multi-attempt logs, archived logs, every container/log selection, download failures and historical artifacts require more coverage. | Actual selected pod logs and downloads were tested; C25 and missing historical fields remain. |
| U38 | HTML/Markdown fidelity | All legacy renderer variants need full stock comparison. | Formatting cases passed; Markdown and HTML sandboxing match stock (C24). |
| U39 | Current deployed UI | The latest archive, inventory and other post-deployment changes have not been rebuilt/deployed/live-accepted on the recovered cluster. | Latest production browser tests use explicitly mocked APIs; do not label them deployed acceptance. |
| U40 | Deployment modes/tenancy | Full multi-user isolation, Kubeflow profiles, service meshes, ingress/proxy layouts, OpenShift, cloud distributions and arbitrary existing clusters are not certified. | Namespace-scoped deployment/RBAC and denied-action checks passed selected cases; multi-user tenant isolation passed live on 2026-11-21 (C27), without Istio or Kubeflow profiles on the local cluster. |
| U41 | SQL reconnect/HA | Argo previously retained a closed SQL session after PostgreSQL restart. Recovery required restarting stateless Argo Server/controller. Automatic reconnect, HA and failover are not proven. | Persistence checks that explicitly restart services are not automatic-recovery proof. |
| U42 | Current local outage | Cause and full recovery are unknown. One successful Kubernetes health check does not close the outage or its effect on in-flight workflows. | No VM restart/prune/deletion was performed; inspect services and pending workflows before resuming live verification. |
| U43 | Scale/performance | Namespace inventory still gathers all summary pages; SDK listings, artifact scans, ConfigMap cache/registry growth, controller throughput and large templates require load testing. | A 256-artifact cached-source case is not a production-scale benchmark. Reduced polling payloads are not established as the outage fix. |
| U44 | Persistence/GC/retention | Full retention, cancellation/failure cleanup, TTL/archive interaction, deleted-version references, backup/restore and recovery across all services remain unverified. | Earlier resource/artifact persistence checks passed a bounded scenario, not every lifecycle. |
| U45 | Packaging/distribution breadth | All supported installation environments, clean offline installs, optional extras, provider dependencies, documentation examples and external consumers have not been exercised. | Wheel/sdist and isolated installed-wheel checks pass; production npm audit reported zero known vulnerabilities at the check time, not a security proof. |
| U46 | Latest full live corpus | The `samples/core` corpus ran cold (caching disabled) plus a default-cache verification on 2026-11-20; see [core samples](core-samples.md). The remaining live coverage, now the `full` tier of `test/e2e/`, has not been rerun since. | That pass found and fixed three regressions from `4518f59ad` (object loop items, PVC stub argv patch, PVC nullable decoding); rerun the remaining programs before claiming the full corpus. |
| U47 | Preview-formats timeout | Resolved: `artifact_preview_formats_pipeline` runs 11 pods strictly sequentially, each pip-installing polars/torch/transformers, and completed `Succeeded` in 15 m 44 s on 2026-11-20. | The runner's 900 s timeout is the limit, not the native stack; raise the timeout or slim the sample's dependencies. |
| U48 | Interrupted nested-condition run | Resolved: `nested_condition.py` passed in the 2026-11-20 cold pass, as did every other previously transport-failed core case. | None. |

### Field-level response parity (resolved 2026-11-20)

Formerly U49–U54. Each field is either populated from a stated native source or
accepted as absent under A09. Stock need not fill every field on every response;
the behavioral comparison of whole responses remains U25.

| Model | Field | Native source |
|---|---|---|
| `V2Run` | `state_history` | PENDING at creation, RUNNING at `status.startedAt`, terminal state at `status.finishedAt` |
| `V2Run` | `scheduled_at` | Argo's `workflows.argoproj.io/scheduled-time` annotation on schedule-created runs; creation time for manual runs, as in stock |
| `V2Run` | `error`, `plugins_*`, `run_details` | Absent, A09 |
| `V2Experiment` | `last_run_created_at` | Newest live or archived run labelled with the experiment; left unset if the run inventory cannot be listed |
| `V2RecurringRun` | `updated_at` | Newest `managedFields` write time on the CronWorkflow; creation time before any update |
| `V2RecurringRun` | `error`, `plugins_input` | Absent, A09 |
| `V2Pipeline` / `V2PipelineVersion` | `error`, `tags`, `package_url` | Absent, A09 |
| `V2PipelineTask` | `state_history` | RUNNING at `startedAt`, terminal state at `finishedAt`; cached and skipped tasks have a single entry |
| `V2PipelineTask` | `scope_path` | Dot path of display names from `root` through Argo's node tree. Loops include Argo's iteration wrapper node, which the task list also exposes, so `root.for-loop-2.iteration.iteration(0:...)` rather than stock's `root.for-loop-2.task` |
| `V2PipelineTask` | `type_attributes` | `iteration_count` on loop groups, `iteration_index` on iterations; `download_to_workspace` absent (C07) |
| `V2PipelineTask` | `lifecycle_message`, `lifecycle_category` | Stock's normalization and classifier ported: transient startup reasons, successful nodes and user-script exits (`Error (exit code N)`) yield no lifecycle message; otherwise image-pull, scheduling, runtime, admission or unknown. The raw node message stays in `status_metadata.message` |
| `PipelineTaskTaskPod` | `uid` | Pod lookup by workflow label on `get_run` of a live run; absent after pod GC, for archived runs, or when pods cannot be listed |
| `InputOutputsIOArtifact` | `producer` | The producing pod recorded in the native artifact identity (one producer per port); outputs carry none |
| `InputOutputsIOParameter` | `producer` | Absent: resolved parameter values do not record their upstream task |
| `V2Artifact` | `created_at` | Producer task finish time; unknown for producers outside the run (cache reuse) |
| `V2Artifact` | `description`, `number_value` | Absent, A09 |

Evidence: `test/native_task_details_test.py` and `test/native_client_test.py`
(red on the previous adapter, green after), and a live `kfp.Client` session
against the OrbStack namespace on 2026-11-20 showing run and task histories,
scope paths, iteration attributes, a pod UID, an experiment last-run time, a
schedule update time and an input producer with its creation time.

## P. External prerequisites, not passing results

| ID | Prerequisite | Unverified scope |
|---|---|---|
| P01 | GPU/TPU/DRA hardware and device plugins | OrbStack is arm64 with no allocatable GPU/TPU; DRA allocation/use was not demonstrated. |
| P02 | Cloud credentials and services | Credentialed cloud/secret sample, GCS execution and provider-specific storage behavior need authorized credentials/services. |
| P03 | Image/runtime architecture | External cloud SDK, legacy TFX and other user images must support the actual architecture and dependencies. An image pull/import failure is not proof of DSL incompatibility. |
| P04 | PVC policy and permissions | Explicit CreatePVC/DeletePVC/workspace tests need suitable StorageClass/access modes and scoped SA permissions. The fixture used `standard` and an owned scoped service account; default component permissions were not broadly elevated. |
| P05 | Browser URL access and auth infrastructure | URL uploads need CORS; SSO/IAP/profile/ingress checks need the corresponding configured environment. |

## B. Baseline failures and questions

| ID | Baseline finding | Classification |
|---|---|---|
| B01 | `samples/core/parallel_join/parallel_join.py` uses invalid `@dsl.container_component()` invocation | Fails stock compilation too; retained as a known xfail, not a native regression. |
| B02 | `samples/core/kfp_env_validation/kfp_env_validation.ipynb` has missing/stale definitions/imports | Fails the captured stock compilation too; retained as a known xfail. |
| B03 | TFX notebook and excluded notebook cells | TFX uses an external legacy runner rather than a captured local DSL definition. Install/submission/timing cells are excluded from the 29-definition corpus. Their compatibility is unverified, not counted as passed. |
| B04 | Root artifact submission, direct Collected iteration and fractional retry semantics | Authoring/API signatures alone do not establish stock end-to-end support. RootDAG parameter-only evidence, the authoring-time direct-Collected failure, and the integer runtime retry factor must be checked before calling these migration regressions. See L01–L03. |
| B05 | `samples/core/resource_spec/runtime_resource_request_gpu.py` sets accelerator type `NVIDIA_TESLA_K80` | Kubernetes rejects the pod: the value is not a standard or fully qualified resource name. Stock's driver also uses the accelerator type verbatim as the resource name, so this is a sample defect, not a native regression; GPU hardware is separately P01. |
| B06 | `samples/core/secret/secret.py` component on `python:3.7` | The SDK runtime (`kfp==2.17.0`) requires Python >= 3.9, so the runtime install fails in that image on stock as well. Credentials remain P02. |

## Evidence and reproduction map

Repository-relative anchors above omit the common prefix `sdk/python/kfp/` for
compiler/client/runtime modules. Tests and programs are retained in the commit;
local `/tmp` logs are supporting workstation evidence, not durable CI artifacts.
No passing CI URL exists for this unpushed checkpoint.

| Area | Retained test/program | Latest local evidence |
|---|---|---|
| Stock definitions | `test/stock_samples_test.py`, `test/e2e/corpus.py`, frozen `stock_samples.json` | `/tmp/kfp-current-stock-offline/`, `/tmp/kfp-stock-native-lint-current.log` |
| Full SDK | `sdk/python/kfp`, `test`, `test/deploy_test.py`, `.github/scripts` | `/tmp/kfp-inventory-projection-full311.log`, `...full313.log` |
| Full UI | `frontend` test:ci (unit, production bundle, offline viewer); live browser suite `frontend/e2e/` on every PR: markdown security, validation errors and real-pod logs, nested importer deep links, optional and artifact-list run forms, dataset/model/classification previews, stock navigation, SDK-to-UI identity and archive round trips, the upstream hello-world lifecycle journey, then the deployment acceptance test. The journey found and fixed three parity defects on 2026-11-20: "Create experiment" from a pipeline page dropped the pipeline before the first run, a run started without an experiment had none instead of stock's Default experiment, and deleted rows lingered until a manual refresh because Argo Server's template listing lags a deletion. 10 of 10 passed in 282 s against OrbStack `kfp-argo`; evidence in `/tmp/kfp-ui-e2e-20261120/` | `/tmp/kfp-inventory-projection-ui-ci.log`; screenshots `/tmp/kfp-experiment-ui-evidence/` are API-mocked UI evidence |
| Default runtime/cache | `test/e2e/test_default_pipeline.py`, `test/e2e/test_stock_runtime.py`, `test/sdk_authoring_compatibility_test.py` | Earlier default/cached/PyPI runtime live checks; not a latest complete rerun |
| Lists/iteration/nullable | `test/e2e/test_artifact_lists.py`, `test/e2e/test_container_optional_inputs.py`, `test/e2e/test_optional_inputs.py`; compiler/runtime tests | Earlier list live logs; `/tmp/kfp-container-optional-full{311,313}.log`; iteration/raw-nullable latest live checks absent |
| Failure/scalars | `test/e2e/test_ignore_failure.py`, `test/e2e/test_container_scalars.py`, compiler/runtime regressions | `/tmp/kfp-ignore-status-live.log`, `/tmp/kfp-native-scalars-live.log` |
| Workspace/settings | `test/e2e/test_workspace.py`, `test/e2e/test_task_config.py`, `test/e2e/test_kubernetes_settings.py` | Workspace passthrough, structured staging and dynamic claim logs; no hardware allocation proof |
| Archive/inventory | `test/e2e/test_experiment_archive.py`, read-only `test/e2e/test_inventory.py`, `native_client_test.py`, `NativeUi.test.ts` | Offline cascade/projection red-green logs; both live programs remain unrun |
| Task DTOs | `test/native_task_details_test.py` | `/tmp/kfp-compressed-status-red.log`, `/tmp/kfp-retry-task-projection-red.log`; later full suites pass |
| `samples/core` corpus | `test/e2e/test_samples.py`; per-sample results in [core samples](core-samples.md) | `/tmp/kfp-core-samples-20261120/` (cold, prerequisite, cache and post-fix reports plus Argo reproducers) |
| Live suite, smoke tier | `test/e2e` with `-m smoke` (16 cases: control flow, failure tolerance, optional and container inputs, typed container outputs, artifact lists, OneOf, default pipeline, inventory, UI interop) | `/tmp/kfp-e2e-smoke-20261120/report.json`: 16 passed against OrbStack `kfp-argo` on 2026-11-20 with components installing KFP from PyPI; the `full` tier has not yet run as a suite |

Live tests are under `test/e2e/` (one pytest suite, see [testing](agents/testing.md)).
Live browser tests are under `frontend/e2e/` and run with the SDK suite on every PR.

### Exact offline validation commands

```sh
uv run --python 3.11 --isolated --frozen --extra test python -m pytest -q \
  sdk/python/kfp test test/deploy_test.py .github/scripts
uv run --python 3.13 --isolated --frozen --extra test python -m pytest -q \
  sdk/python/kfp test test/deploy_test.py .github/scripts
(cd frontend && PLAYWRIGHT_CHANNEL=chrome fnm exec --using=24.22.1 npm run test:ci)
uv build --package kfp --wheel --sdist
```

For generated manifests, use `argo --context orbstack -n kfp-argo lint --offline
<manifest>`. Offline lint is not a workflow submission.

### Live commands

Supply a **non-empty**, appropriately scoped `KFP_TEST_TOKEN` without printing it,
plus `KFP_TEST_HOST` and `KFP_TEST_NAMESPACE`. Check token creation succeeds before
starting a client; do not fall back to another identity. Then run a tier of the
single live suite (see [testing](agents/testing.md)):

```sh
uv run python -m pytest test/e2e -m smoke -p no:randomly --e2e-output /tmp/kfp-e2e-smoke
uv run python -m pytest test/e2e -m full -p no:randomly --e2e-output /tmp/kfp-e2e-full
```

`test/e2e/test_artifact_lists.py` additionally exposes `verify_iteration(client)` for the pending
iteration cases. The sample runner supports explicit `--disable-caching` for cold
verification and `--parallelism` for a bounded submission copy; it does not clear
caches or change SDK defaults. Known stock compilation failures retain a nonzero
exit status, so read the per-case report rather than hiding that exit status.
Do not restart unrelated infrastructure, delete preserved runs/artifacts/PVCs,
loosen RBAC, or claim pending cases passed merely to close this inventory.
