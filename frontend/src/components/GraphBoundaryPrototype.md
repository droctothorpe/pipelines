# Graph boundary prototype — throwaway

**Question:** What should replace the 8px white strip between the graph tabs and canvas?

Three alternatives plus the current design live on the existing pipeline and run detail
routes. No backend/data-flow changes.

**Decision:** The user selected **flush**: remove the strip without changing tab navigation.
The production change is maintained separately on `fix/flush-graph-tabs`.

## Run

From `frontend/`, with the repo's Node/npm versions and dependencies installed:

```sh
npm run prototype:graph
```

This starts the existing mock API on **3001** and the UI on **3002**. Both ports must be
available. It uses only mock data, not the cluster on port 3000. Stop with Ctrl-C.

The launcher builds a development-only preview under `node_modules/.cache/` rather
than using Vite's development dependency optimizer, which currently emits broken
MUI/Emotion initializer references. Restart the command after editing the prototype.
The normal production build is unchanged; prototype rendering is disabled there.

## Compare

- Pipeline: <http://localhost:3002/#/pipelines/details/8fbe3bd6-a01f-11e8-98d0-529269fb1462?variant=flush>
- Run: <http://localhost:3002/#/runs/details/e0115ac1-0479-4194-a22d-01e65e09a32b?variant=flush>

| `variant` | Design | Trade-off |
| --- | --- | --- |
| `original` | Current 8px white strip | Baseline |
| `flush` | Canvas meets the tab divider directly | Smallest change, maximum canvas area |
| `inset` | Canvas gets a 12px frame and rounded corners | Intentional separation, slightly less canvas area |
| `floating` | Segmented tabs float on the canvas | More canvas-first; tabs can cover panned graph content |

The floating bottom bar and ← / → keys cycle through all four options. The URL is
reload-stable and retains other query parameters. Text inputs, editors, and the graph
keep their own keyboard controls. On small screens, the switcher reserves bottom space
so graph controls stay usable. Floating tabs return to document flow on small screens.

Without a recognized `variant` parameter, the original page is unchanged. Non-Graph
tabs keep their original rendering.

## Validation

- TypeScript and focused ESLint checks pass; prototype files pass Prettier.
- Existing `PipelineDetails.test.tsx` and `RunDetailsV2.test.tsx`: **93 tests pass**.
- Headless Chrome checks: all four variants at 1440×900 and 390×844, all four run
  variants, tab switching, keyboard isolation/wrapping, query preservation, and the
  no-parameter baseline. No browser page errors.
- Local screenshots and throwaway browser-check script:
  `frontend/.visual/graph-boundary-prototype/` (ignored by Git).

This explores the seam, not a mobile redesign: the existing toolbar still overflows
on narrow viewports and dense graphs need zooming.

This branch preserves the alternatives as design evidence. Only the selected flush
treatment belongs in production; the prototype launcher, switcher, and other variants
do not belong in the implementation PR.
