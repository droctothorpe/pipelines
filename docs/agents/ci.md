# Native CI

`.github/workflows/native.yml` checks Python 3.11/3.13, schema regeneration,
packaging, the frontend and offline viewer, and a real disposable Kind deployment
on stock's Kubernetes matrix (`kindest/node` v1.33.12 and v1.36.1, passed to
`test/native-deployment.sh` as `KFP_TEST_K8S_VERSION`; keep the list in step with
stock's `e2e-test-frontend.yml` and `kfp-sdk-client-tests.yml`). Stock also ran the
previous Argo minor; native does not, because Argo 4.0.x evaluates a skipped task's
arguments before its `when` and fails the nullable guards (L25 in
`docs/compatibility.md`). `KFP_ARGO_VERSION`, read by `deploy.py` and the CLI install
step, deploys another release for a manual check.
The aggregate `ci-passed` job requires all native jobs to succeed. Backend/Go image
producers, old integration matrices, releases and merge-queue automation are
retired; external branch-protection rules are not changed by this code cleanup.

Security remains covered by CodeQL for Python/TypeScript and the checksum-pinned
OSV source/lockfile scan. Basic issue/contributor/approval automation remains;
it uses trusted workflow-source scripts and does not execute PR code with write
credentials. Preserve its trust boundaries when changing it.

Use immutable action revisions. Read the Node pin from `.nvmrc`; install the npm
version in `package.json`. Native deployment tests use an isolated Kind cluster,
namespace-scoped test tokens, persistent storage, and the repository's Argo pin.
Tokens must be masked before any GitHub log output. Deliberate failed component
cases are assertions, not jobs to retry into success.

Run `actionlint`, the retained SDK/frontend suites, and the actual deployment
acceptance before claiming workflow/deployment changes are verified.
