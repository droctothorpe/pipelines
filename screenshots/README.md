# PR #14751 screenshots

Captured locally from code commit [b7aa119782c3a47ff0c3c7484f26cfd812e69d72](https://github.com/droctothorpe/pipelines/commit/b7aa119782c3a47ff0c3c7484f26cfd812e69d72), using the real DagCanvas in Storybook and Chromium. Node 24.14.0; npm 11.17.0. These are not screenshots of an updated Kubernetes deployment. Runtime statuses in the loop example are fixture data.

## 100 components / 20 nested levels

The three `hundred-components-twenty-levels-*.png` captures are from code commit [85453892186e3a9f01f342f6fabd02293bac40d5](https://github.com/droctothorpe/pipelines/commit/85453892186e3a9f01f342f6fabd02293bac40d5), which adds fixtures and tests without changing the renderer.

- `hundred-components-twenty-levels-default.png`: 100 distinct executable components, five per level, inside 20 nested sub-DAGs. All 120 graph nodes are visible. Default and Expand all are identical because there are exactly 20 groups.
- `hundred-components-twenty-levels-collapsed.png`: Level 10 collapsed, leaving 45 components and nine expanded ancestor groups visible.
- `hundred-components-twenty-levels-detail.png`: the same full graph zoomed/panned to levels 13–20, with Component 100 selected through its complete 20-level path. The overview retains the complete topology; this detail view deliberately shows a magnified subset.
- `hundred-components-twenty-levels-validation.json`: asserted counts, deepest selection, reload behavior, and a local render-and-capture timing (not a performance benchmark).

The existing `scripts/subdag-expansion.smoke.mjs` command below now runs both the 25-group and 100-component/20-level browser scenarios and produces their screenshots.

## 25-sub-DAG comparison

- `twenty-five-subdags-default.png`: default partial expansion, 20 expanded and five collapsed (Groups 20–24 in the bottom row).
- `twenty-five-subdags-full.png`: the same graph after clicking Expand all, 25 expanded and zero collapsed.
- `twenty-five-subdags-comparison.png`: labelled side-by-side composition of those two unmodified browser captures.
- `twenty-five-subdags-validation.json`: asserted browser counts and reload behavior.

Reproduce from `frontend/`:

```sh
npm run storybook -- --ci
# In another terminal:
STORYBOOK_URL=http://localhost:6006 SCREENSHOT_DIR=/tmp/subdag-screenshots \
  node --test scripts/subdag-expansion.smoke.mjs
```

## Refreshed gallery

Each example has an expanded/collapsed pair:

- Nested pipelines and artifacts: collapse Training and evaluation.
- Conditions: collapse both branches.
- Runtime iterations: collapse sweep.0 and sweep.1, retaining the loop.
- Nested loops: collapse for-loop-2 and for-loop-14.
- Exit handler: collapse my-pipeline and condition-1.

`gallery-validation.json` records visible group/node counts, bulk-action checks, and lock/selection checks. All screenshots show the six-button inline-only palette, with no graph breadcrumbs or rendering-mode toggle. Obsolete legacy/deployed captures have been removed from this branch's current tree; earlier pinned commits still retain their original images.

## Validation

- Full frontend unit suite: 135 files, 1,767 tests passed.
- Production build (including UI/server lint and TypeScript), format check, and git diff check passed.
- 25-sub-DAG and 100-component/20-level browser regressions passed. The earlier five-example gallery remains unchanged.
