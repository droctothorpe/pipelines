# PR #14751 screenshots

Captured locally from [code commit 185cbcaf6d2251b0f8ba48c9a5d14a5e277de2f7](https://github.com/droctothorpe/pipelines/commit/185cbcaf6d2251b0f8ba48c9a5d14a5e277de2f7) using the real DagCanvas in Storybook and Chromium, with Node 24.14.0 / npm 11.17.0. Runtime statuses in the loop example are fixture data. These are not captures of a new Kubernetes rollout.

## 25 nested sub-DAGs, two component tasks per level

The former 100-component / 20-level example is replaced by **25 nested sub-DAGs with two executable components each**, 50 components total.

- `twenty-five-levels-default.png`: default partial expansion, levels 1–20 expanded, Level 21 collapsed, and levels 22–25 hidden. 40 component tasks and 21 group nodes are visible.
- `twenty-five-levels-full.png`: after Expand all, all 25 groups and all 50 component tasks are visible.
- `twenty-five-levels-comparison.png`: side-by-side composition of those unchanged overview captures.
- `twenty-five-levels-detail-default.png` / `twenty-five-levels-detail-full.png`: zoomed views making the collapsed Level 21 boundary and its fully expanded descendants legible.
- `twenty-five-levels-detail-comparison.png`: side-by-side composition of those unchanged zoomed captures.
- `twenty-five-levels-validation.json`: verified counts, nesting, deepest selection, and reload behavior.

The overview fits the complete visible topology; the detail images deliberately show magnified subsets.

## 25 sibling/sequential sub-DAGs

- `twenty-five-subdags-default.png`: 20 expanded and five collapsed, with Groups 20–24 in the bottom row.
- `twenty-five-subdags-full.png`: all 25 expanded.
- `twenty-five-subdags-comparison.png`: labelled side-by-side composition.
- `twenty-five-subdags-validation.json`: asserted browser behavior.

## Other refreshed pairs

Nested pipelines/artifacts, conditional branches, runtime iterations, the SDK nested-loop fixture, and the exit-handler example retain expanded/collapsed pairs. `gallery-validation.json` records their counts and interaction checks.

## Reproduction

From `frontend/`, start Storybook, then run:

```sh
npm run storybook -- --ci
# In another terminal:
STORYBOOK_URL=http://localhost:6006 SCREENSHOT_DIR=/tmp/subdag-screenshots \
  node --test scripts/subdag-expansion.smoke.mjs scripts/subdag-interaction.smoke.mjs
```

The interaction test verifies empty group bodies pan the viewport—including nested, selected, and locked groups—while root/nested/collapsed headers, component nodes, and artifact nodes retain their expected drag behavior.

## Validation

- Full frontend unit suite: **135 files / 1,767 tests passed**.
- Production build, UI/server lint, typecheck, format checks, and git diff check passed.
- **Five production-browser checks passed**, including the new 8px white tab-to-graph strip on pipeline and run pages.
- **Three Storybook browser regressions passed**, plus the five-example gallery.
- The local Kubernetes deployment remains at previously verified commit `854538921`; these follow-up changes have not been redeployed.
