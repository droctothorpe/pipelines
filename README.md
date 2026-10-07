# PR #14717 — Timeline MLMD backport screenshots

Screenshots of the production frontend bundle built from commit
`d88d161e1d332fc7fd36f77a202685d413e7c227`, targeting Kubeflow Pipelines `release-2.18`.

- PR: https://github.com/kubeflow/pipelines/pull/14717
- Data: synthetic 35-component layout fixture delivered through mocked MLMD gRPC-web responses, matching the production-bundle smoke-test approach. **Not a live-cluster run.**
- Browser: Chrome 154.0.8037.98, driven by Playwright, device scale factor 1.
- Capture checked that 35 component rows rendered and that no uncaught browser errors occurred.
- Screenshots are unmodified viewport captures. These assets are kept on an evidence-only branch, not in the feature PR.

| Screenshot | Viewport | State |
| --- | --- | --- |
| `01-desktop-overview.png` | 1600 × 900 | Component 8 selected; approximate MLMD timing and unavailable state-history explanation visible. |
| `02-desktop-scrolled.png` | 1600 × 900 | Scrolled to component 34 (last row); inspector remains pinned alongside the chart. |
| `03-short-window.png` | 1600 × 500 | Last row selected; inspector scrolled internally to its footer so graph navigation and sidebar footer remain reachable. |
| `04-narrow-layout.png` | 1000 × 900 | Scrolled near the end; inspector stacks below the chart in normal document flow. |
