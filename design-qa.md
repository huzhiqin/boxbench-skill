# BoxBench live workflow — design QA

final result: passed

## Scope and visual target

Adapt the supplied workflow reference into a working BoxBench test monitor. This is a visual-language adaptation, not a clone of the other product's business workflow. The square icon nodes, dark offset shadows, dotted canvas, serpentine connections, completion badges and animated active state are the source of truth. The app header, run summary, step inspector and logs are intentional additions needed by BoxBench.

- Source: `/var/folders/3t/9gx5fq714g786vgxzl510f140000gn/T/codex-clipboard-bbcc8ded-09ff-47a6-a1f8-dfdf33dae0c1.png` (856 × 520 pixels).
- Final browser screenshot: `../.cache/boxbench-live-qa/desktop-final.jpg` (1244 × 1312 pixels).
- Full graph comparison: `../.cache/boxbench-live-qa/comparison-final.jpg`.
- Focused icon / typography comparison: `../.cache/boxbench-live-qa/focus-final.jpg`.
- Mobile: `../.cache/boxbench-live-qa/mobile.jpg`.
- Failure / skipped states: `../.cache/boxbench-live-qa/error.jpg`.
- Disconnected state: `../.cache/boxbench-live-qa/disconnected.jpg`.

## Viewports, density and state

Used the Codex in-app browser. Desktop responsive check requested 1280 × 900; the final full-page capture reports an effective 1244 × 1312 CSS-pixel surface, DPR 1, and its raster dimensions match that surface. The inspected workflow canvas is 850 × 460 CSS pixels. The reference was normalized to 850 pixels wide (about 516 pixels high), and the implementation graph was extracted at 850 × 460. The source screenshot includes a video play overlay, which is intentionally omitted.

Both reference and final comparison show completed colored nodes, an emphasized running node, and pending pale nodes. BoxBench uses its actual test names and stage order; exact business content and active-node position are intentionally different. Mobile check requested 390 × 844; effective content width was 375 CSS pixels after the browser scrollbar. Document width did not overflow; only the workflow canvas scrolls horizontally.

## Comparison history and fixes

1. Initial desktop comparison (`comparison.jpg`, `desktop.jpg`): P2 — vertical connections passed through node captions at row transitions. Replaced these with curved connections outside the node columns. The final comparison shows clear text and continuous curved paths.
2. P2 — an inactive dark-tone node inherited the highlighted icon color. Restricted the color rule to running/completed nodes; pending icons now consistently use a muted tone.
3. Improved the small monospace node labels from 8px to 10px on desktop and 9px on narrow screens; increased step-description contrast and size. Final focused comparison confirms readable labels without overlap.
4. Failure-state inspection initially followed the last skipped node. Updated follow behavior to focus the failed stage when there is no active step. Final error screenshot and browser accessibility state show the service error and its explanation directly.

No actionable P0/P1/P2 findings remain in the final full-view and focused comparisons.

## Required fidelity surfaces

- **Typography:** System sans stack with PingFang / Microsoft YaHei for Chinese; monospace for test IDs and timers. The Chinese node names and technical labels follow the reference hierarchy. The surrounding dashboard uses a quieter type scale so the workflow remains primary. No clipped headings or overlapping captions were observed.
- **Layout and spacing:** Four-column serpentine graph, three rows; consistent rounded tiles and offset shadows. Sidebar aligns to the graph card. Below 900px the inspector stacks under the workflow; at phone widths the graph scrolls within its card while summary and controls remain in the document width.
- **Colors and tokens:** Off-white dotted canvas; blue, orange and charcoal tiles; lime running outline; green completed badges. Slightly softer saturation than the video reference is intentional for a long-running monitor. Failure and skipped states have distinct badges and explicit accessible names, rather than relying on color alone.
- **Assets:** Actual local Tabler outline SVG icon files, MIT license included; no remote icon/font requests, fake bitmap assets or emoji substitutions. Canvas paths are functional graph visualization driven by state. There are no hero photographs or custom raster illustrations to recreate.
- **Copy:** All business text maps to BoxBench stages. Demo mode is explicit, archived JSON is distinguished from the separately rendered HTML report, and “已执行” is distinguished from benchmark acceptance. Logs are inserted with `textContent`; a script-shaped fixture was displayed as plain text.

## Interactions and runtime evidence

- Clicked a completed node: inspector changed to that stage and stopped following.
- Clicked “跟随当前步骤”: inspector resumed following the active stage.
- Observed changing progress, elapsed time, active outline and moving connector particles.
- Exported a JSON snapshot from the browser; parsed and checked demo flag, exit code and failed stage. Removed the generated fixture download afterward.
- Observed pending, completed, running, failed and skipped node states.
- Stopped the fixture server: connection warning and “等待重连” appeared while preserving the last known state.
- Browser console error checks returned no errors; all visible images loaded.
- Five Python integration tests passed: SSH-compatible shell event separation / unavailable service, loopback HTTP assets and route isolation, child exit-code propagation and journal, multi-model history / interrupted state, and Windows PhaseC against an actual local HTTP/SSE fixture.
- Fresh offline installation and local 1.9.1 → 1.10.0 upgrade both included all live assets.
- Python compilation, JavaScript syntax, Bash syntax and Git whitespace checks passed.

Skill format validation retains the repository's pre-existing top-level `version` field because installation/release scripts depend on it. The stock skill validator rejects that same field on the unmodified baseline. A temporary copy normalized only this field into `metadata.version` passed all remaining skill checks. Runtime scripts require no PyYAML or other third-party Python package.

## Limits and follow-up

No real Linux box or Windows workstation was connected during this implementation. Hardware-specific measurements need the next authorized device run. Independent C13 context-ladder mode still uses its original logs; it is explicitly excluded from the live graph instructions. Multi-model histories are retained in the exported snapshot, while the graph displays the current model.

Implementation checklist: complete. The live demo is retained in the in-app browser for review. P3 follow-up: the tiny English metadata and footer could use a larger type scale if the target audience prefers denser operational text over the reference's light editorial treatment.
