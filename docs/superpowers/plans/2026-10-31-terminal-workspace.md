# Terminal Workspace Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task. No subagents in this side conversation.

**Goal:** Implement the six approved terminal improvements in the requested order: history suggestions, saved sudo credentials, output search, snippets/templates, completion notifications, and tmux recovery.

**Architecture:** Keep xterm.js and existing SSH authentication. Add an opt-in, session-scoped Bash integration for trustworthy prompt/command boundaries. Reuse per-host credential identity binding, SQLite settings and the existing same-origin WebSocket protocol. Keep ordinary terminal mode available and never modify user shell startup files.

**Tech Stack:** React, TypeScript, xterm.js, Python/FastAPI, Bash, optional remote tmux.

**Spec:** Approved feature descriptions in this conversation; acceptance criteria below.

## Global Constraints

- Implement in order 1, 2, 5, 4, 6, 3.
- Preserve SSH config, ProxyJump, native Windows and cached AsyncSSH authentication.
- Passwords must not enter browser state, command history, logs or SQLite.
- Suggestions and templates insert text without executing it.
- Scope history and credentials to the host and resolved account/endpoint.
- No global clipboard monitoring and no SSH disconnect/reconnect notifications.
- Do not restart the user's active service until the completed changes can be reviewed and active sessions are accounted for.

## Review Focus

- Commands containing credentials and inputs to password/full-screen programs must not become history suggestions.
- Control sequences may be split across SSH reads; ordinary output and Unicode must survive unchanged.
- A saved password must not be sent after the SSH endpoint changes or after the prompt/session is gone.
- Refresh/disconnect must detach persistent tmux sessions and preserve their processes.
- Search, shortcuts and suggestion acceptance must not break existing copy/paste, IME, shell editing or resize behavior.

### Task 1: History suggestions and shell boundaries

**Files:** `backend/terminal_shell.py`, `backend/terminal_workspace.py`, `backend/terminal.py`, `frontend/src/terminalSuggestions.ts`, `frontend/src/TerminalDock.tsx`, associated tests.

**Interfaces:** `ShellProtocol.feed(text)` returns visible output plus validated prompt/command events. Workspace stores bounded, filtered, identity-scoped command history. Frontend only tracks editable input after an integrated prompt and offers a prefix suggestion accepted with Right at end-of-line.

- [x] Verify transport preserves the proposed metadata protocol before choosing framing.
- [x] Test split frames, Unicode, command/exit ordering, sensitive commands and history isolation.
- [x] Add a temporary Bash rc file and optional enhanced startup without changing dotfiles.
- [x] Add history access/clear controls and gray suggestion UI; unsupported editing states disable suggestions.
- [x] Verify with a disposable real SSH session and the existing terminal tests.

### Task 2: Saved sudo password action

**Files:** `backend/terminal.py`, `backend/terminal_workspace.py`, `backend/sudo.py`, terminal UI and tests.

**Interfaces:** Per-host opt-in setting plus a session-bound WebSocket sudo action. Backend resolves the credential for the exact current SSH identity and writes it only in an explicitly initiated sudo authentication flow. Browser sees availability/status, never the password.

- [x] Test missing credentials, wrong identity, expired/absent prompt and one-attempt behavior.
- [x] Add “使用已保存的 sudo 密码” action and Alt+Enter; ordinary Enter remains unchanged.
- [x] Retain manual password entry and report validation failure without looping.

### Task 5: Terminal output search

**Files:** terminal UI/styles, dependency manifests and tests.

- [x] Add the official xterm search addon and an in-terminal Ctrl+F panel.
- [x] Add previous/next, count, case and regex controls; Escape closes search.
- [x] Verify search never sends text or shortcuts to the remote shell.

### Task 4: Command snippets and templates

**Files:** `backend/terminal_workspace.py`, `frontend/src/TerminalCommands.tsx`, terminal UI and tests.

- [x] Add bounded per-host command favorites with add/edit/delete and named variables.
- [x] Test missing variables, literal shell punctuation and no automatic execution.
- [x] Offer training/log/Conda examples and insert-only preview into the active prompt.

### Task 6: Completion notifications

**Files:** shell event handling, workspace settings, terminal UI and tests.

- [x] Measure foreground command duration and exit status from confirmed shell events.
- [x] Add configurable per-host duration threshold and notification toggle, defaulting to long tasks only.
- [x] Notify once per completed command; never on disconnect/reconnect or replayed metadata.
- [x] Show command result/duration in the terminal toolbar without persisting raw output.

### Task 3: tmux recovery

**Files:** remote startup, workspace session records, terminal picker and tests.

- [x] Add explicit persistent session creation and reconnection using project-prefixed tmux names.
- [x] Detect missing tmux and show installation guidance; do not install automatically.
- [x] Preserve commands during detach and restore the same session after a new browser connection.
- [x] Make closing a tab detach; ending a persistent session requires a separate explicit action.

### Final verification

- [x] Run relevant backend and frontend tests and a production frontend build.
- [x] Validate real SSH history, search, templates, completion and tmux detach/reattach using disposable data; test credential routing with dummy passwords.
- [x] Update user documentation and summarize actual platform/feature limits.
- [x] Inspect live session impact before activating the backend update.

## Verification receipts

- Backend: `python -m pytest tests -q` — 164 passed, 1 Windows tray smoke test skipped by design.
- Frontend: 82 tests and TypeScript/Vite production build.
- Real OpenSSH/ConPTY: Bash prompt/command metadata and Unicode on a Linux accelerator host; a tmux 3.4 task survived closing its SSH client, finished detached, and was reattached with its original output/status. All dedicated test sessions were ended.
- Browser: prefix suggestion and Right acceptance; official SearchAddon found 2 matching output lines; template variables previewed and filled without executing; persistent session created, closed and recovered. A 2-second failing command generated one event with exit code 1; reattachment did not repeat it.
- Password routing: isolated WebSocket test used a dummy credential, covering opt-in, missing prompt, one attempt and changed endpoint. No real credential was printed or exposed to the browser.
- Escape: covered in the component handler test. This Chrome automation environment swallowed Escape even in a separate minimal key-event probe; browser Enter/next/previous and the Close button were exercised normally.

## Follow-up: reconnect and duplicate terminal

- Added session-closed prompt plus one-key reconnection. The triggering key is consumed; output stays in the existing xterm instance. Old socket events cannot overwrite a new connection, concurrent retries are coalesced, and full-screen input modes reset without clearing scrollback.
- Added duplicate-terminal action using the latest confirmed Shell cwd. New ordinary sessions are independent; persistent sessions create a new tmux ID in the same cwd. Unknown directories are reported instead of silently using home.
- Bash prompt hooks append and import the account's existing HISTFILE, respecting disabled history and preserving the original command exit status. Software history remains shared by the existing identity-scoped workspace broadcaster.
- Native SSH validation used two terminals and a private disposable HISTFILE: a new terminal read the source history, later commands were imported at the next prompt, and Up recalled them. Browser validation confirmed /tmp cloning and consumed-key reconnect. All validation sessions/history files were cleaned up.
- Final suite: 164 backend tests passed, 1 tray smoke test skipped; 82 frontend tests passed; production build passed.

## Follow-up: H200 Shell alias detection

- Verified an Ubuntu GPU host declares /bin/sh, and /bin/sh resolves to /usr/bin/bash 5.1.16. The old basename-only guard incorrectly rejected it before checking Bash capabilities.
- Added executable identity comparison for Shell aliases while retaining ordinary-shell fallback for genuinely different executables. No login-shell/account configuration was changed.
- Validation: 19 terminal backend tests passed, including alias identity and separate-shell rejection. A dedicated native SSH session on that host emitted prompt/start metadata and confirmed /tmp under enhanced mode; its disposable HISTFILE/session was cleaned up.
- The updated detection applies when opening a new terminal with the updated backend; existing remote Shell processes keep their original hooks.
