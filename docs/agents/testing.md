# Testing and formatting

Three layers: offline pytest, the frontend suite, and one live end-to-end suite.

## Offline

```sh
uv sync --frozen --extra test --extra lint --extra codegen
uv run python -m pytest -q sdk/python/kfp test
uv run ruff check sdk/python/kfp samples/argo-native hack/generate-python.py test
uv run ruff format --check sdk/python/kfp samples/argo-native hack/generate-python.py test
```

Repeat SDK validation on Python 3.11 and 3.13. Build a wheel and sdist; verify the
wheel includes the native runtime, public Client/native adapters and both schema
bindings, and excludes retired service API transports and local runners. Generated
bindings are committed so installing a wheel requires neither protoc nor a backend.
`test/` holds the offline files directly; `test/e2e/` is collected too but every
test in it skips unless `KFP_TEST_HOST` is set. `test/data/` holds the frozen stock
baselines (sample definitions and client signatures).

## Frontend

With the pinned Node/npm versions:

```sh
cd frontend
npm ci
npm run test:ci
```

The native production-bundle test checks both entrypoints, API boundaries and
memory-only credentials. The real standalone viewer smoke covers offline and
sandboxed rendering, graph/inspector state and watch recovery. Keep tests at those
boundaries rather than restoring old RPC-model fixtures.

## End to end

`test/e2e/` is the single live suite for the SDK against a deployed native
installation. Each module drives the public `kfp` client, then reads the real
workflow, pods or artifacts. Point it at a cluster and pick a tier:

```sh
kubectl --context orbstack -n kfp-argo port-forward svc/kfp-argo-ui 3003:80 &
export KFP_TEST_HOST=http://127.0.0.1:3003 KFP_TEST_NAMESPACE=kfp-argo
export KFP_TEST_TOKEN="$(kubectl --context orbstack -n kfp-argo create token argo-ui-editor --duration=2h)"
uv run python -m pytest test/e2e -m smoke -p no:randomly          # what CI runs, about ten minutes
uv run python -m pytest test/e2e -m full -p no:randomly           # everything else, an hour or more
uv run python -m pytest test/e2e -m full -p no:randomly -k samples  # the stock sample corpus only
```

Markers: `smoke` runs on every pull request through `test/native-deployment.sh` on a
disposable Kind cluster; `full` is the rest; `prerequisite` cases skip unless
`KFP_TEST_PREREQUISITES=1` because they need GPUs, cloud credentials or a
PVC-capable account (`KFP_TEST_SERVICE_ACCOUNT`); `no_cluster` marks the few tests
that need no deployment. `KFP_TEST_IMAGE` names a prebuilt image carrying this SDK
so components skip the PyPI install; CI sets it to the content-addressed demo image.
`KFP_TEST_DISABLE_CACHING=1` forces a cold sample pass. `--e2e-output DIR` (default
`/tmp/kfp-e2e-<timestamp>`) receives compiled manifests and `report.json`, which the
inventory cites as evidence. Run with `-p no:randomly`: tests are independent, but a
fixed order keeps reports comparable.

Adding a case: put the pipeline in the test module (or under `test/e2e/pipelines/`
when an offline test also imports it), assert on the run and on Argo state through
`e2e.support`, mark the tier, and call `record(...)` with the run id. The samples
under `samples/` are user-facing documentation and are never edited for tests;
`test/e2e/samples.py` holds their inputs and expectations.

Expected failure cases must fail for the expected reason; an arbitrary terminal
state is not a passing result. Do not reset unrelated clusters or artifact stores.
