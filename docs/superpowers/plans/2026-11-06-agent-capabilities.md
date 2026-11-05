# Agent capabilities and approval implementation plan

**Goal:** Enable local files/Shell, web research, subagents and shared approval modes.
**Architecture:** All real operations use the shared MCP dispatcher. A per-run approval controller is propagated by context variables to embedded MCP and external engine bridges. Virtual framework files remain separate from real host files. Modes: ask, full, read_only. Session grants are explicit canonical roots; Shell always asks in ask mode unless an execution grant exists. Rejections, cancellation and restart never execute pending calls.
**Constraints:** Preserve existing host scoping, credentials, cancellation and demo isolation. Never mutate live user data during tests. Existing unrelated frontend theme/dist changes remain intact. Chinese and English UI strings.

- [x] Task 1: shared permission controller, pending approval records and decision endpoint; tests for binding/replay/read-only/cancel.
- [x] Task 2: capability MCP tools for local files/Shell, web search/read, bounded outputs and cancellation; test path/network boundaries.
- [x] Task 3: composer permission/root controls, approval cards and SSE types; demo remains synthetic.
- [x] Task 4: runtime subagent enablement, inherited controller, external bridge parity, user documentation.
- [x] Task 5: integration tests, full regression for shared dispatcher changes, frontend build, diff check, isolated browser validation where available.

Ruling: User approved the design and implementation; execute without another design approval. Use subagent-driven development for independent modules. No automatic push or live backend restart.

Validation: latest full run passed: 1120 backend tests passed, 15 skipped; 364 frontend tests passed; 14 tooling tests passed. Frontend production build and git diff --check passed. Isolated browser approve/reject flows observed.
