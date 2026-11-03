# Desktop auto-updater implementation plan

> **For agentic workers:** Use superpowers:executing-plans, implementing the independent native/backend/frontend domains in parallel.

**Goal:** Add signed GitHub Release updates to v0.1.1 with startup/manual checks, user-initiated download and installation, and coordinated graceful shutdown of the bundled backend.

**Architecture:** The native Tauri process owns updater metadata, downloaded bytes and verification. Guarded custom IPC is available only to the main trusted workbench page, never demo/quick/browser clients. Frozen tray runtimes publish an owner-protected local control receipt; authenticated update shutdown exits the tray and its server without killing the installer frontend. Release CI signs artifacts and produces latest.json using a private key stored outside Git and in GitHub encrypted secrets.

**Tech Stack:** Tauri updater/Rust, React/TypeScript, Python FastAPI/tray runtime, GitHub Actions.

**Spec:** Approved chat scope: implement the public-release updater discussed with the user; v0.1.0 users manually install v0.1.1 once. Preserve repository privacy until user opens it.

## Constraints
- No GitHub access token in client software. Fixed public HTTPS feed and signed artifacts only.
- Signing private key never enters repository, output logs or software. Public key is committed.
- Do not install updates, shut down the running user's backend, or kill existing desktop processes during validation.
- Installation is explicit, checks all webviews for unsaved work/active terminals, and only shuts down matching frozen runtime gracefully.
- Retain user data and credentials. Unknown/source-owned services cause a safe refusal, not process termination.

## Tasks
- [x] Add capability-authenticated graceful update shutdown and ownership tests.
- [x] Add native signed update state/check/download/install, trusted-origin checks and all-window close guards.
- [x] Add startup/manual update UI, progress, notes, errors/retry and browser/demo restrictions.
- [x] Set v0.1.1, create/protect signing key, configure CI secrets/artifacts/feed and release tests.
- [x] Review integration; run backend/frontend/Rust checks, fake update-feed/signature verification and signed Windows packaging.
- [x] Record tested boundaries and publish the bootstrap updater release without replacing v0.1.0.

## Review focus
- Incomplete/invalid/no-newer feed, failed downloads/signatures and duplicate operations must not install.
- Missing/forged/stale backend receipt and backend timeout must not stop unrelated processes.
- Unsaved files, active terminal sessions, pending workspace writes or unresponsive webviews block install.
- Private repository/network errors are visible on manual checks but quiet on background checks.
- Failed installation restarts only the exact runtime that this updater safely stopped.
