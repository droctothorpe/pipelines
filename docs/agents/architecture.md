# Architecture

For SDK or UI changes, follow the compatibility target in
[SDK compatibility](../sdk-compatibility.md). Preserve public authoring/client
interfaces and default-on caching behind native adapters; only IR-specific
interfaces and local execution are excluded. The earlier bounded prototype is
not the acceptance standard for this work.

`GraphComponent` captures DSL tasks, groups and channels. The native compiler
lowers those objects to WorkflowTemplates, Workflows and CronWorkflows. Argo owns
execution, status, transfer, cache and archive; the Python bridge runs inside each
component container. The static UI/proxy has no application database or backend.

The two protobuf bindings in `kfp.pipeline_spec` and `kfp.kubernetes` remain shared
authoring/configuration schemas. `dsl/component_definition.py` serializes portable
container definitions for the SDK loader/image builder; it does not register tasks,
compile pipeline IR or contact a server. This is distinct from the removed REST
API definitions and old pipeline IR builder.

Artifacts are key-only; Argo's namespace repository chain places them, the
submitter binds that bucket into the run, and the runtime checks the binding.

The browser reads Kubernetes ConfigMaps for experiments and Argo resources for
versions, runs and schedules. Argo Server provides hydrated/offloaded status and
archive/artifact access. UID is run identity. Cache metadata retains the original
producer. Tokens stay in memory and namespace roles enforce permissions. In
multi-user mode the proxy authorizes the gateway-named user per request with a
SubjectAccessReview, the stock API server's model, and acts with its own account.

`test/native_cleanup_test.py` guards the retired-service boundary. The repo has no
Go execution backend, KFP controllers, legacy REST transports, or in-process
runners. A backwards-compatible `kfp.Client` facade over native APIs belongs in
the SDK; its presence is not a return of the old backend.
