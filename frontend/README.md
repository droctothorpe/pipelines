# Native KFP frontend

The app retains the stock KFP sidebar, toolbars, tables, forms, selectors and run
presentation. The app and offline viewer share graph, artifact-card, inspector and
log widgets. Both web entrypoints load `src/argo.tsx` and the hash router in
`src/components/Router.tsx`. `Native*` pages bind the presentation to Kubernetes
and Argo Server; there is no KFP REST client, Node application server or mock backend.

Use the Node/npm pins in `.nvmrc` and `package.json`:

```sh
npm ci
npm run test:ci
```

`npm start` uses the deployed authenticated proxy at `http://127.0.0.1:3003` by
default (`KFP_NATIVE_PROXY` overrides it). See `../samples/argo-native/README.md`
for deployment, namespace-scoped authentication and real acceptance tests.

Rebuild the checked-in SDK viewer assets with `npm run build:viewer` after changing
shared UI modules or dependencies. The native bundle and offline/sandbox browser
tests exercise the actual built code, including API and credential boundaries.

## Stock presentation reference check

Serve an unmodified frontend build from stock commit
`7780f12acfbde9f16169c7fcbfdfb6c3ef5432ea`, then run:

```sh
npm run build
KFP_STOCK_UI_URL=http://127.0.0.1:3012 PLAYWRIGHT_CHANNEL=chrome \
  node --test scripts/stock-ui-parity.smoke.mjs
```

This compares the five list pages against the actual stock bundle using identical
empty inventories at 1280×720 and 390×844. Screenshots and `report.json` are saved
under `/tmp/kfp-stock-ui-parity` (`KFP_PARITY_OUTPUT` overrides this). The test
requires zero pixels differing by more than 20 RGB levels. It is an optional
reference check, not a claim that every data state or unsupported backend feature
has full parity. `native-bundle.smoke.mjs` also checks populated run graphs,
inspector tabs, metadata, artifact downloads, logs, the timeline and token handling.

A read-only deployed navigation check is available as `scripts/stock-ui.smoke.mjs`;
set `ARGO_UI_URL`, `ARGO_NAMESPACE` and `ARGO_READER_TOKEN`. Full authenticated
lifecycle verification uses `scripts/argo-deployment.smoke.mjs`.
