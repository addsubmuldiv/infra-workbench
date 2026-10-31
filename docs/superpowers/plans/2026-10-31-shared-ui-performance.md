# Shared UI performance follow-up

Scope: desktop-entry; retain existing unrelated edits. Windows and macOS use the same frontend; no OS-specific rendering assumptions.

1. Freeze and measure the current production frontend as baseline. Reconcile unchanged JSON snapshots, memoize derived inventory statistics, defer device grouping until open. Preserve notification polling and fresh/stale updates.
2. Persist terminal geometry after gestures, keeping resize/keyboard/viewport behavior. Verify final frame and no storage writes during a gesture.
3. Experiment with xterm WebGL, retain DOM fallback on unsupported/context-loss cases and constrain GPU resources. Compare identical fixed ANSI output, throughput, ACK latency, tab response, private working set. Retain only supported changes with acceptable results.
4. Split optional feature bundles and measure startup. Do not change Rust startup semantics without timing evidence.
5. Run frontend regression tests/build, Windows real-client benchmarks, and a final independent review. Record macOS runtime validation as unavailable unless a real Mac runner is available.

Validation: original 48-host/384-device fixture, actual visible Edge and Release WebView2, three alternating trials, four terminals at 256 KiB/s total and eight at 1 MiB/s total. Existing Python backend is excluded. Compare distributions; do not promise speedups based on code inspection.

Progress: baseline frozen at work/performance-round2/before; full baseline benchmark running. No commits/staging of unrelated work.

Task 1: implementation and focused regression checks passed (18 state/overview tests). Unchanged server_time is a readiness-only value in current UI; other JSON fields still reconcile on every poll. No visibility-based suspension of notification polling.
Task 2: geometry test reproduced per-pointer storage writes, then passed with persistence gated until gesture end (5 window tests).
Task 3: experimental active-only WebGL; DOM fallback on import, constructor, activation or context loss; asynchronous imports invalidated on switch/unmount. Not yet accepted as default pending measurements. Existing terminal behavior suite: 31 passed.
Task 4: optional precision/files/settings/assistant views split into lazy chunks; inventory/home remains eager. No native startup semantics changed.
Ruling: retain baseline benchmark's full 3-round load schedule; do not run frontend builds or the full test suite concurrently with measured loads. Short focused tests during early development are recorded in work/performance-round2 logs; treat close performance differences cautiously.

Ruling: WebGL remains diagnostic opt-in (`?terminal-renderer=webgl`), DOM remains default. The initial 4/8-terminal smoke confirmed output/ACK completion and real GPU context-loss fallback, but did not demonstrate an advantage; its short tab samples were slower than baseline. Do not extrapolate short smoke measurements or force a GPU renderer on untested Macs. Keep a reproducible opt-in experiment, and measure the shipped default separately.

Compatibility: explicit es2020/safari15 build target; browserId uses cryptographic getRandomValues fallback, and terminal code no longer requires Array.at. Windows WebKit 26.6 port passed initial/lazy views, 480/800/1440 layouts and real WS output twice: normal APIs and missing randomUUID/Array.at/WebGL2; 129344 bytes ACKed in each case, no page errors. This does not replace native Mac testing. Final source suite/build: 176 passed / tsc+Vite passed. Independent read-only review requested.

Independent review: no important source/runtime issues. Follow-up CI review found missing trigger coverage for scripts/check-desktop-flows.cjs; added the path. Expanded WebKit flow and final packaging still pending after load measurements. UI 3-trial results: unchanged13s median script desktop150.49->9.43ms, browser193.44->9.42ms; commits7->1 on both. Every200-move drag writes200->1; drag script timing is not consistently faster on both clients.

Raw files:
- before full: work/desktop-benchmark/run-2026-10-31T15-04-22-047Z/results.json
- before UI: work/desktop-benchmark/ui-2026-10-31T15-29-19-525Z/results.json
- after UI: work/desktop-benchmark/ui-2026-10-31T15-31-50-622Z/results.json
- after full (running): work/desktop-benchmark/run-2026-10-31T15-34-29-250Z/results.json
- final frontend snapshot: work/performance-round2/after (DOM default; must match after UI/full hashes)
- experimental WebGL snapshot: work/performance-round2/experimental; GPU smoke: work/desktop-benchmark/smoke-2026-10-31T15-22-54-489Z/results.json; GPU context-loss smoke: work/desktop-benchmark/ui-2026-10-31T15-21-23-753Z/results.json

Remaining: finish formal full output (owned exec session69277, log work/performance-round2/after.log), run expanded WebKit files/editor flow and --flows-only on real desktop/browser, rebuild Windows package, generate docs/benchmarks/2026-10-31-performance-followup.json using scripts/compare-performance-followup.cjs and write docs/PERFORMANCE-FOLLOWUP.md, link from docs/DESKTOP.md. No staging/commits of unrelated work; original backend left running. Do not rerun completed full baselines.

Complete: formal before/after validation passed (24 load phases, all sent bytes ACKed, no pending messages/errors/disconnects/long tasks). Engine versions, viewports, visible states and matching UI/full snapshot hashes verified. Final frontend regenerated by packaging matches measured after hash.
Complete: expanded WebKit normal/missing-API cases passed real HTTP upload receipts20bytes, Chinese editor save, terminal echo/ACK and lazy pages. Actual visible desktop/browser --flows-only passed same operations: work/desktop-benchmark/run-2026-10-31T15-52-42-514Z/results.json. Earlier flow harness failures fixed by waiting for running terminal and checking upload bytes at local HTTP fixture (WebKit request interception did not expose the Blob body). No product source change was needed.
Complete: Windows package build exit0; frozen runtime self-test passed. Installer desktop/src-tauri/target/release/bundle/nsis/Infra Workbench_0.1.0_x64-setup.exe. Report docs/PERFORMANCE-FOLLOWUP.md and validated data docs/benchmarks/2026-10-31-performance-followup.json generated; docs/DESKTOP.md links report. YAML parsed successfully (15 steps, Windows/macOS ARM/Intel); remote CI and native Mac runtime not executed. No remaining authorized implementation work; no commits or merges performed.
