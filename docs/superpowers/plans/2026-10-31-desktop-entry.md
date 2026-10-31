# Desktop Entry Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Add a Windows/macOS desktop entrance with the existing web UI, retain browser access and background monitoring, and measure performance before making changes.

**Architecture:** A Tauri window loads the existing loopback origin, so HTTP, WebSocket, relative URLs and same-origin checks remain intact. An existing backend is reused; otherwise a platform-specific Python tray/menu-bar runtime is started independently of the window. Production builds bundle a Python runtime, while source builds use the project virtual environment.

**Tech Stack:** Tauri 2, Rust, WebView2/WKWebView, React/TypeScript, existing Python/FastAPI service, PyInstaller.

**Spec:** User-approved design in this chat: shared UI, responsive layout, second entrance, measured performance; Windows and macOS are required. Branch: `desktop-entry`.

## Global Constraints

- Preserve pre-existing uncommitted work; do not commit unrelated changes or private data.
- Never stop or replace an existing backend automatically.
- Keep API and WebSocket at the original loopback origin; do not relax origin checks.
- Closing the desktop window must not stop monitoring, reservations or SSH sessions owned by the backend.
- Build each platform on that platform; macOS signing/notarization requires the owner's signing identity.
- Report unverified Mac behavior and measured vs synthetic performance explicitly.

## Review Focus

- An occupied port belonging to another program must not receive privileged desktop access.
- Rapid double launches must reuse one backend and one desktop window.
- Paths with spaces/non-ASCII characters must work without shell interpolation.
- WebView download/upload, clipboard, keyboard and navigation behavior need actual UI verification.
- Closing/reopening, minimized windows, retina/DPI and offline startup must remain usable.

### Task 1: Baseline

- [x] Run existing frontend/backend tests and record pre-existing failures.
- [x] Measure a synthetic large machine set in an isolated browser, blocking all API mutations; open the actual small inventory read-only in the native window.
- [x] Record rendering, frame intervals, long tasks and sidebar drag behavior with the same scenario for before/after.

### Task 2: Desktop shell and runtime

Files: `desktop/src-tauri/{Cargo.toml,build.rs,tauri.conf.json,src/main.rs}`, `desktop/package.json`, `backend/desktop_runtime.py`, desktop entry scripts.

- [x] Test platform selection, data paths, packaged/source argument dispatch, health identity and source/blob origin policy. Cold tray/menu-bar startup remains an acceptance item.
- [x] Create the Tauri window with single-instance activation and window-state persistence.
- [x] Implement tray/menu-bar startup without a browser; verify reuse of an existing healthy service on Windows.
- [x] Keep navigation at loopback; external links open in the system browser without native privileges.
- [x] Provide loading/retry errors and verify native close confirmation for unsaved editor state on Windows.

### Task 3: Measured optimization

Files depend on baseline evidence; avoid speculative framework changes.

- [x] Reproduce the sidebar drag hotspot with the measurement script before changing it.
- [x] Add off-screen card rendering containment and rerun the same baseline scenario.
- [x] Run frontend tests and production build; verify responsive layout and terminal behavior.

### Task 4: Distribution and verification

Files: platform build scripts, `docs/DESKTOP.md`, desktop CI workflow.

- [x] Implement native Windows/macOS packaging without user data; Windows frozen helper self-test verifies actual HTTP/assets and ConPTY. Mac build execution remains pending.
- [x] Build Windows application and installer; run and inspect the actual window.
- [x] Verify Windows coexistence, upload/download, resizing, duplicate launch and unsaved close behavior. Clipboard and real SSH acceptance remain pending.
- [x] Configure macOS ARM64/x64 native builds; distinguish CI configuration from a completed Mac test.
- [x] Record tests, measurements, known limits and concrete entry points in docs/DESKTOP-VALIDATION.md.

## Execution record

- Branch created and renamed to `desktop-entry` as requested.
- Frontend baseline: 162 passed.
- Backend baseline: 432 passed, 8 skipped, 1 failed (`test_password_login_then_provision_and_verify_key[False]`, Windows temporary private-key ACL). No desktop changes existed at this point.
- User authorized installation of Rust/C++ build tools and requested Windows/macOS support.
- Reviewer findings fixed: real Windows main(argv) dispatch (regression RED→GREEN), remote close command ACL (real window verified), missing WKWebView download handler (implementation added, Mac acceptance pending).
- Ruling: keep browser and WebView preferences separate, matching existing storage; machine/reservation data comes from the shared backend. Wrong choice would require a later preferences synchronization endpoint.
- Ruling: retain existing source defaults and use persistent user directories for packaged installs. Existing data is not silently copied; IWB_DATA is the explicit migration mechanism.
- Ruling: use self-contained native platform builds, not cross-compilation of Python bundles. Mac artifacts and signing are not claimed without a Mac run.
- No unrelated pre-existing edits were reverted or included in a commit.
