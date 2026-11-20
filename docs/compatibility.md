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
| A01 | Compiled execution format | Native WorkflowTemplate/Workflow/CronWorkflow replaces PipelineSpec execution IR and KFP PipelineVersion CRDs. Historical IR manipulation/import is outside the agreed target; recompile original Python. Portable container component definitions remain supported. |
| A02 | Backend and wire protocols | KFP backend/controllers, old REST/gRPC service transports and per-component driver infrastructure remain removed. Public SDK/UI outcomes are the target, not the old internal endpoints or storage layout. |
| A03 | Local execution | Local runners/local execution remain removed. Passing `execute_locally=True` does not restore them. |
| A04 | Missed recurring occurrences | Native Argo recovers at most one missed occurrence within its recovery window, not every missed occurrence. No backfill dispatcher. |
| A05 | Artifact-list staging architecture | A consumer init-container may stage runtime-sized collections using the installed Argo downloader. No additional copy pods; storage credentials remain init-only. This is an accepted implementation mechanism, not permission to drop artifact behavior. |
| A06 | System Logs tab | The obsolete KFP System Logs tab was removed at the user's request. Task logs, details and I/O remain. |
| A07 | Release infrastructure | The old release/merge-queue machinery was retired with approval. Native CI/security/contributor checks are not a replica of the retired release system. |
| A09 | Response fields owned by the retired backend | Accepted 2026-11-20. These stock response fields stay unset because their source no longer exists; they are not fabricated. `V2Run`: `error`, `plugins_input`, `plugins_output`, `run_details` (MLMD context ids). `V2RecurringRun`: `error`, `plugins_input`. `V2Pipeline`/`V2PipelineVersion`: `error`, `tags`, `package_url`. `V2Artifact`: `description`, `number_value` (MLMD custom properties). `PipelineTaskTypeAttributes.download_to_workspace` (C07). Pod `uid` after the pod is garbage-collected or for archived runs. Formerly C19 and U49–U54; the fields Argo can supply are populated, see the field table. |
| A08 | Artifacts page scope | Accepted 2026-11-20. The Artifacts page lists artifacts from the latest 50 runs and shows a truncation notice; it is not a global artifact catalog or index. Artifacts remain reachable through their runs, which is where they are used. Maintaining an index would add state the native stack otherwise avoids, for a page that is rarely the entry point. Formerly C22. |

## C. Confirmed gaps or narrower functionality

### Authoring, runtime, artifacts and Kubernetes

| ID | Surface | Current difference | Evidence / boundary |
|---|---|---|---|
| C01 | Nested graph task retry | **Resolved 2026-11-20 as parity.** A retry policy on a nested pipeline task now compiles with a warning and is not applied, which is what stock does: its Argo compiler neutralizes DAG retries because retrying a DAG re-runs the whole subgraph. Inner task retries are unaffected. | `compiler/argo_compiler.py:compile_component`; `argo_compiler_test.py` |
| C02 | Nested graph custom caching | **Resolved 2026-11-20, beyond stock.** A custom cache key on a nested task scopes every inner task's cache identity (stock records the key but never applies it). Disabling caching on a nested task already propagated. Pipelines without nested keys keep their existing fingerprints. Verified live: same key cached, new key executed. | `argo_compiler.py:leaf`; `argo_compiler_test.py` |
| C03 | Nested graph platform overrides | **Resolved 2026-11-20, beyond stock.** Static kfp-kubernetes settings on a nested task reach every inner pod (stock drops them): dictionaries merge, lists accumulate, the inner task wins on conflicts. Settings bound to pipeline parameters or task outputs are rejected with a message naming the task, since inner tasks cannot resolve them. Verified live: a secret env and node selector set on the nested task appeared in the inner pod. | `argo_compiler.py:_kubernetes_config`; `argo_compiler_test.py` |
| C04 | Cross-boundary failure-tolerant inputs | **Resolved 2026-11-20.** A failure-tolerant consumer inside a condition, loop or nested group may now consume a producer outside the group. The group item tolerates the producer's failure, forwards a guarded value and a `kfp-present-<port>` flag through every template on the way down (loop fan-out wrappers included), and the consumer applies its own fallback. Verified live: with a failing producer the run ends FAILED while the consumer in a condition, a two-iteration loop and a nested condition succeeded with its default; with a succeeding producer it received the value. Remaining limit L16. | `compiler/argo_continuation.py:arguments`, `argo_groups.py:thread_presence`; `argo_compiler_test.py` |
| C05 | Raw-container failure-tolerant inputs | Optional/no-default failure-tolerant container inputs are rejected; an explicit non-None default is required. Python cleanup support is broader. | `compiler/argo_compiler.py`, `optional_after_failure` guard |
| C06 | Workspace deployment defaults | Workspace PVC access modes must be supplied explicitly. Stock deployment-provided workspace defaults are not bound into the native compiler. | `compiler/argo_workspace.py:configure` |
| C07 | Importer download to workspace | `download_to_workspace=True` is explicitly rejected. Ordinary podless URI importers do not reproduce workspace materialization. | `compiler/argo_importer.py:compile_importer` |
| C08 | Workspace TaskConfig in raw containers | Workspace volume passthrough currently requires a Python component. | `compiler/argo_task_config.py:project` |
| C09 | Dynamic structured TaskConfig in raw containers | Dynamic structured projection requires the Python runtime bridge; raw/container equivalents are not lowered. | `compiler/argo_structured.py:finalize` |
| C10 | Mixed dynamic affinity | Mixed dynamic node-affinity terms are rejected. Single dynamic affinity JSON and static affinity are a narrower implementation. | `compiler/argo_kubernetes.py:lower` |
| C11 | Mixed dynamic resource claims | Mixed dynamic DRA declarations are rejected. Single dynamic declarations do not cover the mixed case. | Same lowerer, explicit mixed-claim guard |
| C12 | Entrypoint-only raw artifact-list consumers | A raw list consumer needs an explicit executable command. Image-entrypoint-only consumers are rejected. | `compiler/argo_artifact_lists.py:add_staging` |
| C13 | Storage/provider coverage | Pipeline artifact roots accept S3/GCS; importers and list staging accept S3/GCS/HTTP(S). OCI/modelcar and repository-plugin list staging are not implemented. Other stock provider/integration combinations are not substitutes for these supported paths. | `argo_artifacts.py`, `argo_importer.py`, `argo_staging.py`, `client/_artifact_repository.py` |
| C14 | Stock default storage policy | The native compiler defaults to `s3://argo-artifacts` for the bundled deployment. It does not discover or migrate an existing stock KFP server's default pipeline-root/storage policy. Explicit root overrides are implemented. | `compiler/compiler.py:Compiler.__init__`, `argo_artifacts.py` |
| C15 | Non-Kubernetes platform extensions | Only the retained kfp-kubernetes settings have native lowering. Other platform settings are rejected; preserving their serialized schema does not execute the corresponding service. | `argo_compiler.py:platform` |
| C16 | Launcher debugging barriers | Stock launcher-specific before/after/error pause hooks are not reproduced. Native suspend/resume is not the same in-container debugging interface. | Native bootstrap/runtime replaces the launcher |

### SDK, lifecycle, UI and integrations

| ID | Surface | Current difference | Evidence / boundary |
|---|---|---|---|
| C17 | Backend plugin inputs | Run plugin inputs explicitly raise `NotImplementedError`; plugin output models exist but there is no corresponding native plugin execution path. | `client/_native.py:_workflow_spec` |
| C18 | Certificate-only full history/artifacts | Direct Kubernetes authentication supports resource operations. Argo-only archive/artifact/history requests still need an authenticated Argo endpoint. `list_runs` and experiment archival also consult archive history; Kubernetes-only full-history separation is unfinished. | `client/_transport.py`, `_native.py`; U29 |
| C19 | Historical task/MLMD detail | **Resolved 2026-11-20** for everything Argo can supply: task and run state history, scope path, iteration attributes, lifecycle category and stock's lifecycle-message normalization, pod UIDs while pods exist, artifact creation times and input producers, experiment last-run time, schedule update time and run scheduled time. The remainder is accepted as A09. | `client/_task_details.py`, `client/_native.py`, `test/native_task_details_test.py`, `test/native_client_test.py`; field table below |
| C20 | Atomic experiment archival | Native archival is ordered, retryable multi-resource mutation, not the stock database transaction for experiment/run state. Some children may change before a reported failure. Concurrent run/schedule creation is not atomically fenced. | `_native.py:_experiment_storage`, `NativeUi.ts:setExperimentStorage` |
| C21 | UI package upload breadth | The UI importer accepts a labelled native WorkflowTemplate document, narrower than the SDK's native YAML/JSON/ZIP/tar and resource-kind handling. URL import depends on browser CORS. | `frontend/src/lib/NativeImport.ts`, `pages/NativeUpload.tsx` |
| C22 | Artifact discovery breadth | Moved to accepted departure A08 on 2026-11-20. | `frontend/src/lib/NativeQueries.ts:useArtifactInventory` |
| C23 | Legacy visualizations | Full legacy UI-metadata/table/dashboard routing and managed TensorBoard behavior are not restored. Dataset/Model previews and classification viewers do not replace all legacy viewers. | `NativeArtifactPreview`, `NativeClassificationMetrics`, `NativeInspectors` |
| C24 | Markdown/security rendering | Raw HTML, unsafe links, external images and active-format images are blocked. Content depending on those features will not render as in a permissive stock viewer. These restrictions must not be removed silently. | `components/viewers/MarkdownViewer.tsx` |
| C25 | UI log breadth | **Resolved 2026-11-20.** Running tasks stream live from their pod with `follow` and no tail limit; finished tasks load the complete archived `main-logs` artifact, which also serves runs whose workflow object or pod is gone; a finished task with nothing archived falls back to the full pod log while the pod exists. Verified in the browser against the OrbStack namespace: live lines grew without refresh and ended at 365 lines, the finished task read 361 archived lines, and a deleted run read its archive. Not restored: stock's per-container selection and log search. | `frontend/src/lib/NativeUi.ts:streamTaskLogs`, `NativeRunDetails.tsx:useTaskLogs`, `NativeUi.test.ts`, `native-bundle.smoke.mjs` |
| C26 | Migration and export/import | No migration service for existing stock run databases, metadata histories or stored pipeline catalogs, and no complete namespace export/import path, is supplied. Preserving the local native fixtures is not a stock-data migration test. | Native architecture and deployment scope |
| C28 | Explicit ordering across group boundaries | Found 2026-11-20 while closing C04: a task inside a condition or loop that calls `.after(task_outside_the_group)` fails to compile with "Dependency crosses a group boundary", with or without `ignore_upstream_failure()`. Stock lifts such a dependency to the enclosing group. Data dependencies across the boundary work; only the explicit ordering edge is missing. Likely fix: lift external `.after()` targets onto the group item in the ancestor scope, as the presence flags now are. | `compiler/argo_groups.py:build`; reproducer in the 2026-11-20 session notes |
| C27 | Kubeflow integration/session UX | Full profiles/central-dashboard integration and stock SSO/session UX are not restored. Native namespace/bearer-token UI access is the tested path. | `frontend/src/components/Router.tsx`, native proxy/auth adapters |

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
| L16 | Mixed tolerance inside a group | When a group contains both a failure-tolerant and an ordinary consumer of the same outside producer, compilation is rejected with a message naming the output and group, because the group as a whole must either wait for the producer to succeed or tolerate its failure. Stock evaluates each task individually. Make every consumer in the group failure-tolerant, or move the ordinary consumer out. |
| L15 | Individual UI run archival | The UI's individual-run archive helper allows only terminal runs, while SDK archival and experiment cascading can archive active runs without termination. Exact stock UI selection/guard behavior still needs comparison. |

## U. Compatibility not established

### Compiler, runtime, storage and configuration

| ID | Area | What remains uncertain | Existing coverage / next evidence |
|---|---|---|---|
| U01 | Artifact-list iteration | Latest single-item staging and nested list iteration have not run live. | Compiler/stager/runtime tests and native lint pass; `artifact_lists.py:verify_iteration` remains unrun. |
| U02 | Nullable raw-container argv | None/empty/literal-null handling, nested Concat and staged-list IfPresent need actual execution. | BusyBox fixture `container_optional_inputs.py`; 25 temporary pinned Expr/Sprig evaluations are only expression-level evidence. |
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
| U13 | TaskConfig matrix | Every field combination, nested scope, apply-to-task mode and older SDK runtime combination is not verified. | Selected CPU/env/selectors, external-only workspace/DRA projection passed; C08–C11 remain. |
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
| U22 | Latest experiment cascade | SDK/UI archival, partial failure/retry, late-created runs and parent-first restoration need live verification. | Unit and mocked production browser tests pass; `experiment_archive.py` is retained but unrun. |
| U23 | Compact inventory API behavior | Latest field projection, metadata-only negotiation, count-aware paging, cache lag and identity reconciliation need live verification on the deployment. | Upstream source, unit and mocked browser tests pass; read-only `inventory.py` is unrun. |
| U24 | Latest task projection | Gzip snapshots and nested retry/validation pod ownership need live proof, especially compressed/offloaded histories and retries. | New red/green tests pass; prior typed task snapshots were checked live before these edits. |
| U25 | Complete response/exception parity | Full DTO field availability, error codes/categories, I/O producer classification, child hierarchy, cancellation state and serialization equivalence remain incomplete. | The field parity table below records what is populated and A09 what is accepted as absent; whole-response and exception equivalence per operation is still uncompared. |
| U26 | Filtering and pagination semantics | All filter operators/field aliases/types, empty inventories, ordering ties, paging under mutation and old cursor/error expectations lack complete baseline comparison. | `_listing.py` has retained tests; old wire tokens are not preserved. |
| U27 | Remaining lifecycle edges | Default-experiment deletion protection, orphan membership, deletion races, already-deleted resources, default/shared version selection, unregistered template adoption and all clone paths need review. | Basic CRUD/UID/name-reuse tests pass. No new destructive probes were run to close these questions. |
| U28 | Recurring trigger semantics | Seconds-bearing cron, time zones/DST, start/end boundaries, outage windows, concurrency saturation/queued-vs-skipped occurrences and enable/disable races need full comparison. | Periodic/default-enabled/cron configuration and selected executions passed. Six-field zero-seconds normalization is narrower than arbitrary seconds cron. A04 only accepts missed-occurrence catch-up, not every other scheduling difference. |
| U29 | Authentication matrix | SSO/IAP/OIDC/Dex/cookies, proxy/TLS variants, token expiry/refresh under live load, impersonation expectations, in-cluster deployments and archive-path credentials are not all proven. | Certificate and SA direct Kubernetes execution, reader denial, and offline credential tests passed. C18/C27 remain. |
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
| U38 | HTML/Markdown fidelity | Sandboxing/security restrictions, allowed embedded content and all legacy renderer variants need full stock comparison. | Formatting/security cases passed; C24 is intentional current restriction, not blanket parity. |
| U39 | Current deployed UI | The latest archive, inventory and other post-deployment changes have not been rebuilt/deployed/live-accepted on the recovered cluster. | Latest production browser tests use explicitly mocked APIs; do not label them deployed acceptance. |
| U40 | Deployment modes/tenancy | Full multi-user isolation, Kubeflow profiles, service meshes, ingress/proxy layouts, OpenShift, cloud distributions and arbitrary existing clusters are not certified. | Namespace-scoped deployment/RBAC and denied-action checks passed selected cases. |
| U41 | SQL reconnect/HA | Argo previously retained a closed SQL session after PostgreSQL restart. Recovery required restarting stateless Argo Server/controller. Automatic reconnect, HA and failover are not proven. | Persistence checks that explicitly restart services are not automatic-recovery proof. |
| U42 | Current local outage | Cause and full recovery are unknown. One successful Kubernetes health check does not close the outage or its effect on in-flight workflows. | No VM restart/prune/deletion was performed; inspect services and pending workflows before resuming live verification. |
| U43 | Scale/performance | Namespace inventory still gathers all summary pages; SDK listings, artifact scans, ConfigMap cache/registry growth, controller throughput and large templates require load testing. | A 256-artifact cached-source case is not a production-scale benchmark. Reduced polling payloads are not established as the outage fix. |
| U44 | Persistence/GC/retention | Full retention, cancellation/failure cleanup, TTL/archive interaction, deleted-version references, backup/restore and recovery across all services remain unverified. | Earlier resource/artifact persistence checks passed a bounded scenario, not every lifecycle. |
| U45 | Packaging/distribution breadth | All supported installation environments, clean offline installs, optional extras, provider dependencies, documentation examples and external consumers have not been exercised. | Wheel/sdist and isolated installed-wheel checks pass; production npm audit reported zero known vulnerabilities at the check time, not a security proof. |
| U46 | Latest full live corpus | The `samples/core` corpus ran cold (caching disabled) plus a default-cache verification on 2026-11-20; see [core samples](core-samples.md). The other live programs under `test/sdk_compatibility/` have not been rerun since. | That pass found and fixed three regressions from `4518f59ad` (object loop items, PVC stub argv patch, PVC nullable decoding); rerun the remaining programs before claiming the full corpus. |
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
| Stock definitions | `test/stock_samples_test.py`, `test/sdk_compatibility/sample_corpus.py`, frozen `stock_samples.json` | `/tmp/kfp-current-stock-offline/`, `/tmp/kfp-stock-native-lint-current.log` |
| Full SDK | `sdk/python/kfp`, `test`, `samples/argo-native/deploy_test.py`, `.github/scripts` | `/tmp/kfp-inventory-projection-full311.log`, `...full313.log` |
| Full UI | `frontend` test:ci; production `native-bundle.smoke.mjs` | `/tmp/kfp-inventory-projection-ui-ci.log`; screenshots `/tmp/kfp-experiment-ui-evidence/` are API-mocked UI evidence |
| Default runtime/cache | `default_pipeline.py`, `stock_runtime.py`, `test/sdk_authoring_compatibility_test.py` | Earlier default/cached/PyPI runtime live checks; not a latest complete rerun |
| Lists/iteration/nullable | `artifact_lists.py`, `container_optional_inputs.py`, `optional_inputs.py`; compiler/runtime tests | Earlier list live logs; `/tmp/kfp-container-optional-full{311,313}.log`; iteration/raw-nullable latest live checks absent |
| Failure/scalars | `ignore_failure.py`, `container_scalars.py`, compiler/runtime regressions | `/tmp/kfp-ignore-status-live.log`, `/tmp/kfp-native-scalars-live.log` |
| Workspace/settings | `workspace.py`, `task_config.py`, `kubernetes_settings.py` | Workspace passthrough, structured staging and dynamic claim logs; no hardware allocation proof |
| Archive/inventory | `experiment_archive.py`, read-only `inventory.py`, `native_client_test.py`, `NativeUi.test.ts` | Offline cascade/projection red-green logs; both live programs remain unrun |
| Task DTOs | `test/native_task_details_test.py` | `/tmp/kfp-compressed-status-red.log`, `/tmp/kfp-retry-task-projection-red.log`; later full suites pass |
| `samples/core` corpus | `test/sdk_compatibility/run_samples.py`; per-sample results in [core samples](core-samples.md) | `/tmp/kfp-core-samples-20261120/` (cold, prerequisite, cache and post-fix reports plus Argo reproducers) |

All live programs in the table are under `test/sdk_compatibility/` unless another
path is given. Live browser programs are under `frontend/scripts/`.

### Exact offline validation commands

```sh
uv run --python 3.11 --isolated --frozen --extra test python -m pytest -q \
  sdk/python/kfp test samples/argo-native/deploy_test.py .github/scripts
uv run --python 3.13 --isolated --frozen --extra test python -m pytest -q \
  sdk/python/kfp test samples/argo-native/deploy_test.py .github/scripts
(cd frontend && PLAYWRIGHT_CHANNEL=chrome fnm exec --using=24.22.1 npm run test:ci)
uv build --package kfp --wheel --sdist
```

For generated manifests, use `argo --context orbstack -n kfp-argo lint --offline
<manifest>`. Offline lint is not a workflow submission.

### Pending live commands (not executed as part of this inventory)

Supply a **non-empty**, appropriately scoped `KFP_TEST_TOKEN` without printing it,
plus `KFP_TEST_HOST` and `KFP_TEST_NAMESPACE`. Check token creation succeeds before
starting a client; do not fall back to another identity. Then, for example:

```sh
uv run --python 3.11 --isolated --frozen --extra test python \
  test/sdk_compatibility/container_optional_inputs.py
uv run --python 3.11 --isolated --frozen --extra test python \
  test/sdk_compatibility/experiment_archive.py --output /tmp/kfp-experiment-archive-live
uv run --python 3.11 --isolated --frozen --extra test python \
  test/sdk_compatibility/inventory.py --output /tmp/kfp-inventory-live.json
```

`artifact_lists.py` additionally exposes `verify_iteration(client)` for the pending
iteration cases. The sample runner supports explicit `--disable-caching` for cold
verification and `--parallelism` for a bounded submission copy; it does not clear
caches or change SDK defaults. Known stock compilation failures retain a nonzero
exit status, so read the per-case report rather than hiding that exit status.
Do not restart unrelated infrastructure, delete preserved runs/artifacts/PVCs,
loosen RBAC, or claim pending cases passed merely to close this inventory.
