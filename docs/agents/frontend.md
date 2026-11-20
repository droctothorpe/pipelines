# Frontend

The application is React/TypeScript/MUI with TanStack Query and shared React Flow
widgets. `src/argo.tsx` and the offline viewer are the entrypoints. Argo/Kubernetes
browser adapters replace the retired REST API clients. Both `index.html` and
`argo.html` load the native application. There is no Node server or mock backend.

The Router asks for a namespace bearer token unless `/config.json` reports a
single-user proxy; keep that fallback so older proxies and offline bundles still
prompt. Task logs are an async generator: running tasks stream Argo Server's
newline-delimited log endpoint with `follow`, finished tasks read the archived
`main-logs` artifact; keep both paths and never reintroduce a tail limit. Use the pinned Node/npm versions and `npm run test:ci`. Rebuild the checked-in
SDK viewer assets after changing shared widgets. The native production-bundle
smoke checks endpoint boundaries and credentials; the deployment smoke uses real
namespace-scoped tokens and checks denied mutations.

Use effects only for external synchronization. Derive display data during render,
perform mutations in event handlers, and preserve selections across refreshes.
Test graph expansion/selection and error recovery when changing those paths.
Prettier uses single quotes, trailing commas and a 100-character line width.
