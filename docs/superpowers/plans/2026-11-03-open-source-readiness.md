# Open-source readiness implementation plan

> **For agentic workers:** Use superpowers:executing-plans to implement each independent deliverable.

**Goal:** Ship a reviewable desktop release path, consistent permissions documentation, and an isolated interactive demo with a spotlight guide.

**Architecture:** Reuse the existing PyInstaller/Tauri packaging. The browser demo installs an in-memory API adapter before workspace initialization and blocks unsupported network transports. The guide targets real workbench controls; no real credentials, model calls, SSH or user storage enter demo state.

**Tech Stack:** React/TypeScript, Python/FastAPI, Tauri/NSIS, GitHub Actions.

**Spec:** User-approved scope in this chat: installation wizard, isolated demo, spotlight onboarding, documentation and release checks.

## Global constraints
- Preserve existing real-mode authorization and machine scoping.
- Demo must not migrate or delete existing local preferences.
- No API keys or host credentials in artifacts, demo fixtures or reports.
- Do not claim clean Windows or macOS hardware validation without running it.

## Tasks
- [x] Write regression tests for demo network isolation, workspace isolation and simulated resource transitions.
- [x] Implement in-memory fixtures, reservation mutations, sample files, explicit demo assistant and terminal.
- [x] Integrate entry/exit/reset and accessible spotlight tour in the existing interface.
- [x] Verify desktop packaging and add versioned draft Release with checksums.
- [x] Audit current/history release inputs and reconcile Chinese/English permission and installation documentation.
- [x] Run targeted tests, frontend production build, browser smoke and desktop build where available.
- [x] Review changes and record limitations before reporting completion.

## Review focus
- Demo loaded on the same origin as a real backend: all unsupported APIs and sockets fail closed.
- Existing local preferences are not imported, removed or replaced by demo.
- Missing guide targets, narrow viewports, keyboard escape/Tab, replay and skip remain usable.
- A deleted or offline fake host and changed reservation do not cause a real network fallback.
- Release versions agree with package metadata; untested platforms remain labelled.

## Validation outcome

Frontend: 241 tests; related backend: 38 tests; release manifest: 2 tests; Rust: 8 tests. Normal and standalone demo builds, frozen Windows runtime self-test and NSIS packaging succeeded. Browser checks covered the guided demo in desktop/mobile layouts and with Array.at/structuredClone disabled. See docs/RELEASE-VALIDATION.md for platform limitations. Clean Windows installation and native macOS acceptance remain pending; public Pages/Release publication has not been performed.
