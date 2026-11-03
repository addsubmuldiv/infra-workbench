# AI workbench v0.1.2 Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development to implement and review each task sequentially. User approved implementation, individual commits, push and release build.

**Goal:** Integrate Codex and the approved AI/terminal features into the existing workbench.

**Architecture:** Keep the existing assistant, chat persistence, SSE and shared MCP dispatcher. Add engine adapters, scoped context and reusable tool-backed workflows. Remote work remains behind server-side machine and credential boundaries.

**Tech Stack:** Python/FastAPI, official Codex App Server JSON RPC, React/TypeScript/xterm, existing Tauri desktop.

**Spec:** User-approved roadmap in this chat. Explicitly deferred: terminal splits/workspace layouts, global transfers, dual-pane files, AI-assisted training log ingestion.

## Global constraints

- Implement sequentially; verify and commit each feature before starting the next.
- Reuse existing business MCP tools; embedded agents never receive SSH passwords/private keys.
- Machine scope is bound by the server, not model parameters. Native local tools have their own restrictions.
- Preserve existing API profiles, Deep Agents, skills, streaming, cancellation and persistent remote jobs.
- No secrets in git, output or release assets. No production remote writes for testing.
- Final version 0.1.2; push commits and version tag, build Windows plus Apple Silicon / Intel macOS release using existing workflow. Update artifacts are signed; Apple Developer ID signing/notarization is not configured.

## Review focus

- Engine/session transitions cannot reuse broader permissions or stale remote targets.
- Disconnect, cancel and process exit must not report incomplete operations as successful.
- Untrusted terminal/file output cannot grant permission or initiate automated writes.
- Automatic triggers need explicit opt-in, bounded executions and protection from recursive loops.
- File/command actions quote paths and retain existing permission and credential protections.

## Tasks and acceptance

1. [x] **Codex integration** — `backend/codex_*.py`, `backend/agent_chat.py`, assistant engine selector. Real installed CLI text/tool/continuation/cancel smoke; mocked protocol and scope tests; commit.
2. [x] **Terminal context to AI** — terminal selection/screen buffer attachment and explicit read limits, machine/session/cwd provenance, assistant launch/draft handoff; tests for truncation and scope; commit.
3. [x] **Port forwarding/service entry** — managed loopback local SSH forwarding, per-host start/stop/status, port conflict reporting, TensorBoard/Jupyter/custom service links, backend lifecycle cleanup; real local tunnel smoke where practical; commit.
4. [x] **Keyword highlighting** — configurable literal terminal rules with training presets, persistent preferences, safe bounded rendering and full-screen terminal behavior; tests/build; commit.
5. [x] **Reusable automation** — user-inspectable deterministic workflows over approved MCP tools, manual runs first, opt-in connect/output triggers only when reliable events exist, bounded run logs/cancel; AI create/edit via tools and skills; tests; commit.
6. [x] **Chat branches and steering** — branch before last turn preserves original, restores draft, clears engine opaque state; executing Codex can accept supplemental instructions, other engines explicitly report capability; tests; commit.
7. [x] **Additional agents** — integrate available external CLI agent through documented machine-readable protocol, shared MCP and chat events, honest capability/detection errors; tests and installed-runtime smoke; commit.
8. [x] **Images and terminal shortcuts** — safe remote image preview and archive extraction command fill without autoexecution, correct path tracking/platform support; tests/build; commit.
9. [ ] **Release** — whole-change review, full backend/frontend/release checks, update docs/changelog and all version manifests to 0.1.2, build frontend, commit, push, tag and build GitHub release. Record exact artifact/workflow status.

## Progress / rulings

- User added macOS packaging during release: cancelled the Windows-only run and dispatched release workflow `41605640001` with `include_macos=true`, preserving the existing immutable v0.1.2 code tag. Both Mac architectures and Windows now build in GitHub runners. Native Mac device acceptance remains pending.
- Release preflight: all eight approved features committed; v0.1.2 manifests synchronized. Full Python suite 742 passed / 11 skipped, frontend 272 passed, Rust 13 passed, release helpers 5 passed. WebKit normal/legacy flows pass after adding the new automation response to the synthetic fixture. Real Codex also passed against all 77 Workbench MCP tools using an isolated empty inventory. GitHub push/tag/build remain pending until these release changes are committed.
- Starting commit: a857649; worktree clean; feature branch `codex/ai-workbench-v012`.
- Installed Codex 0.147.0 is logged in with ChatGPT; verify actual local protocol instead of assuming Netcatty's version-specific interface.
- Ruling: work on a feature branch in the clean shared checkout to reuse the installed build environment; no changes to main until validated.
- Ruling: optional API/SDK credentials will not be invented; unavailable external agent runtimes must have explicit setup status.

Task 1 implementation: local Codex App Server, authenticated scoped real MCP, isolated native tools, engine picker, model discovery and scope-safe resume. Targeted tests and frontend build pass. Live CLI initialize/account/model/MCP inventory validated; follow-up `16be5a8` inherited the OS proxy for the isolated subprocess and verified real CLI MCP tool calls, thread continuation and cancellation; see `docs/CODEX.md`.

Task 2: explicit selection/visible-screen capture, bounded Unicode plain text and provenance, removable preview/draft handoff including standalone terminal assistant. Independent server attachment/scope validation and credential scrubbing; both engines receive untrusted attachment data. Targeted backend, full frontend tests and TypeScript/Vite build verified. No continuous output feed or automatic execution.

Task 3: saved per-host loopback-only service rules, TensorBoard/Jupyter/custom HTTP presets, explicit start/stop/delete and active-only URL. Reuses verified password sessions or isolated native OpenSSH config, preserves jump aliases without inherited forwards. Removal/shutdown cleanup; service MCP tools use host scope and explicit-request descriptions. Real local AsyncSSH and native OpenSSH echo tunnel roundtrips, bind-failure diagnostic, host removal race, validation and MCP scope tests pass; frontend 252 tests and TypeScript/Vite build pass. Remote HTTP health and Jupyter token acquisition are outside tunnel status. No production remote changes.

Task 4: bounded literal keyword highlighting uses xterm cell widths and bottom-layer decorations, with marker cleanup and parsed-write invalidation even at the scrollback cap. Bilingual toolbar settings persist the master switch and per-rule text/color/enabled state across existing sessions; presets separate error/warning colors from informational NCCL/checkpoint/success. Alternate buffer is excluded. Frontend tests and TypeScript/Vite build pass; see `docs/TERMINAL-HIGHLIGHTS.md`.

Task 5: saved inspectable workflows with at most 8 allowlisted business MCP calls; AI draft tools and bundled skill, settings management/manual runs, trusted terminal connect/output triggers with explicit UI activation (output read-only), cooldown/concurrency bounds, schema/scope checks at save and execution, scrubbed bounded history and cancellation. Background jobs/handoffs stop as awaiting verification; cancellation does not terminate remote jobs. Targeted backend tests, frontend 256 tests and TypeScript/Vite build pass. See docs/AUTOMATION.md. No production SSH writes.

Task 6: branch before latest user turn preserves original and restores message/terminal attachments/skills/scope as draft; scope-bound server model snapshot only, cleared provider state, bounded explicit Codex branch seed, active branch rejection. Codex in-flight turn/steer uses runtime-only connection map, run/turn checks, scrubbed bounded instructions and per-chat serialization; visible supplement receipts, cancellation cleanup, stale409 with draft retention. Other engine explicitly disabled. Real CLI synthetic blocking-MCP steer accepted, then tool/process cleanup verified without SSH; final steer output intentionally not asserted. Backend branch/scope/seed/race tests, frontend 259 tests and TypeScript/Vite build pass. See docs/CODEX.md.

Task 7: Claude Code and OpenCode CLI adapters reuse scoped MCP, skill snapshots, traced tool calls and chat streaming/cancel. New CLI sessions receive bounded server history for the current engine/scope epoch; no native session persistence or steering. Windows trusted-package runtime resolution, protected ephemeral config, plugin/native-tool denial and OpenCode resolved-config checks. Claude Code 2.1.226 real synthetic MCP/text/continuation/cancel passed without SSH. Task-local OpenCode 1.19.5 flags and config isolation passed; one bounded150s model attempt timed out without tool/text, explicitly unverified and not detected as global install. Backend targeted57 tests and frontend265 tests/build pass. See docs/EXTERNAL-AGENTS.md.

Task 8: opt-in shared-workspace terminal image switch, pinned official addon-image 0.9.0 SIXEL/IIP with pixel/payload/cache bounds and a guarded parser adapter that expires late decoder storage on timeout/disposal. Unified Ctrl/Command path links fill quoted archive extraction commands only at confirmed empty prompts, with no newline; relative paths need known cwd. Frontend 272 tests and TypeScript/Vite build pass. Real local Edge Chromium and WebKit (without createImageBitmap) rendered synthetic PNG/SIXEL, corrupt-image continuation/download-ignore checks pass; actual delayed bitmap after timeout/disposal cannot mutate storage. No production SSH or native macOS validation. See docs/TERMINAL-IMAGES-ARCHIVES.md.
