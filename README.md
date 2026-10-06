# Timeline PR #14696 — screenshot evidence

Screenshots captured on 2026-10-06 from a real local OrbStack Kubernetes deployment of PR revision `263e3437b80529a62e629c1bac2429ad9bbb9fbd`. The deployed native ARM64 images were built by CI run `37487846216`; its merge commit has the same source tree as the PR revision.

These are actual browser captures, not mockups or synthetic API responses. This screenshot-only branch is separate from the PR implementation so the images do not enlarge its code diff.

[Validation results](https://github.com/kubeflow/pipelines/pull/14696#issuecomment-6021121329)

| Screenshot | Scenario |
|---|---|
| `multi-layer-uncached-timeline.png` | First viewport of a completed workflow with 31 uncached component executions |
| `nested-loops-live.png` | Nested-loop workflow while component spans are active |
| `subdags-nested-graph.png` | Navigation to an exact task in a loop iteration, inner pipeline, and conditional sub-DAG |
| `exit-failure-timeline.png` | Deliberately failed task and successful exit handler |
| `cache-hit-timeline.png` | Actual cached rerun with three cached component tasks |
| `sticky-timeline-900.png` | Bottom-row selection with the details panel still visible in a 900px-high viewport |
| `sticky-timeline-500.png` | Height-bounded details with internal scrolling in a 500px-high viewport |

The sticky-panel captures use production frontend bundle `f092cd5f828b2cd10d2bde825942132ee745c886` over the same real backend and completed 31-component run. The local frontend image is `sha256:61ef57674a96f1617de1462fcc06657341934a62c1d62c8d627d047cb02387be`.
