# PR #14751 screenshots

Captured from [code commit 94e466b88a34e136b09b1999f224bf20cd895fbf](https://github.com/droctothorpe/pipelines/commit/94e466b88a34e136b09b1999f224bf20cd895fbf) using the real DagCanvas in local Storybook and Chromium. Node 24.14.0 / npm 11.17.0. These are not captures of a new Kubernetes rollout.

## Expansion persistence and defaults

- Normal pipeline-version and run graphs persist expansion mode and individual expanded/collapsed IDs in localStorage, scoped to their stable resource IDs.
- Saved choices survive remounts, page reloads, and browser restarts when storage is available. Malformed/blocked/full storage does not prevent rendering or in-memory interaction.
- Uncached graphs expand at most **10 sub-DAGs**, shallower and upstream groups first. Expand all and Collapse all override this default.
- This is a **DAG-count limit, not a width limit**.
- Storybook examples intentionally omit persistent resource IDs, so screenshot tests start from reproducible defaults. Production-bundle browser tests verify persistence on both pipeline and run pages.
- Manual drag positions are not persisted.

## 25 nested sub-DAGs, two component tasks per level

- `twenty-five-levels-default.png`: levels 1–10 expanded, Level 11 collapsed, and levels 12–25 hidden. 20 component tasks and 11 group nodes are visible.
- `twenty-five-levels-full.png`: after Expand all, all 25 groups and 50 component tasks are visible.
- `twenty-five-levels-comparison.png`: side-by-side composition of those unmodified overview captures.
- `twenty-five-levels-detail-default.png` / `twenty-five-levels-detail-full.png`: zoomed views showing the collapsed boundary and full-depth descendants.
- `twenty-five-levels-detail-comparison.png`: side-by-side composition of the zoomed views.
- `twenty-five-levels-validation.json`: verified counts, nesting, deepest selection, and ephemeral Storybook reload behavior.

The overview fits the complete visible topology; detail images deliberately show magnified subsets.

## 25 sibling/sequential sub-DAGs

- `twenty-five-subdags-default.png`: 10 expanded and 15 collapsed, with Groups 10–24 in the bottom three rows.
- `twenty-five-subdags-full.png`: all 25 expanded.
- `twenty-five-subdags-comparison.png`: labelled side-by-side composition.
- `twenty-five-subdags-validation.json`: asserted browser behavior.

## Other refreshed pairs

Nested pipelines/artifacts, conditions, runtime iterations, the SDK nested-loop fixture, and the exit-handler example have explicitly expanded/collapsed pairs. Runtime statuses are fixture data. `gallery-validation.json` records counts and interaction checks.

## Reproduction

From `frontend/`, start Storybook, then run:

```sh
npm run storybook -- --ci
# In another terminal:
STORYBOOK_URL=http://localhost:6006 SCREENSHOT_DIR=/tmp/subdag-screenshots \
  node --test scripts/subdag-expansion.smoke.mjs scripts/subdag-interaction.smoke.mjs

# Actual page reload/persistence and 8px strip checks against the production bundle:
npm run build
node --test scripts/production-bundle.smoke.mjs
```

## Validation

- **136 test files / 1,782 tests passed**.
- Production build, UI/server lint, typecheck, formatting, and git diff check passed.
- **Five production-browser checks passed**, including both graph-page reloads retaining Collapse all, Expand all and individual exceptions, plus the 8px white tab-to-graph strip.
- **Three Storybook browser regressions passed**, including group-body panning versus header/node dragging, plus the five-example gallery.
- Local Kubernetes remains at previously deployed commit `854538921`; the latest follow-ups have not been redeployed.
