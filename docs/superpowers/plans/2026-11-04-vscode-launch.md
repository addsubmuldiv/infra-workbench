# VS Code Launch Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Open a machine in local VS Code after optional SSH tunnels are connected.

**Architecture:** Add a persisted `before_vscode` flag to tunnel rules (default false). A prepare route starts selected tunnels, the UI waits with cancellation and a deadline, and the launch route rechecks readiness before invoking the local VS Code CLI without a shell. Failures permit explicit retry or opening without waiting. Existing tunnels remain independent.

**Tech Stack:** FastAPI, asyncio subprocess, React/TypeScript.

**Spec:** User-approved VS Code button and tunnel prerequisite flow in this chat; no remote-folder preference in this increment.

## Global Constraints
- Preserve all unrelated current work, including concurrent SSH import fixes.
- No user SSH config or VS Code settings mutation, credential transfer or automatic extension installation.
- Use existing SSH alias; direct hosts preserve username and port through Remote SSH authority metadata.
- Never execute user-controlled shell commands; Windows `.cmd` must resolve to the application CLI instead of cmd.exe.
- Cancel stops waiting/opening; independently managed tunnels remain connected.
- Local application availability is checked before starting any tunnel.

## Review Focus
- Old tunnel rules missing the new flag must remain usable.
- Failure, timeout or cancellation must not open VS Code automatically.
- Readiness is checked again immediately before launch.
- Spaces, punctuation and case in target data cannot become CLI options or shell syntax.
- Missing VS Code, changed/deleted hosts and concurrent state updates must produce actionable failures.

### Task 1: Backend
- [x] Add tests for launcher discovery, safe argv, alias/direct-host authority, old-rule migration, selected tunnel prepare and launch readiness.
- [x] Observe failing tests, implement backend/vscode.py and integrate app routes.
- [x] Extend TunnelRequest and migration with `before_vscode`.

### Task 2: UI
- [x] Add tunnel checkbox, VSCodeButton and cancellable wait orchestration in frontend/src/vscode.ts.
- [x] Add meaningful orchestration tests for success, failure, timeout, cancellation and skip.
- [x] Add localized machine button and status dialog.

### Task 3: Validation
- [x] Run targeted backend and frontend regressions, production build and browser flow using isolated fixture.
- [x] Review changes and update usage docs.

Ruling: Continue in the existing worktree and retain unrelated edits. No automatic commit, push or live backend restart.

Validation: 35 targeted backend tests passed; 309 frontend tests passed; frontend production build passed. After the final environment-only launcher change, all 9 VS Code backend tests passed again. The installed Windows VS Code CLI --version exited 0 using its versioned installation layout. An isolated browser/SSH fixture confirmed wait-before-dispatch and bind-failure/explicit-skip flows; its editor dispatch was mocked to avoid opening user windows. No real remote VS Code authentication was attempted.

Review: fixed a missing prepared-target check on explicit skip; added frontend and backend regressions. Independent follow-up review found no remaining important issues. Native macOS launch remains unverified.

Pre-commit integration: rebuilt against main 9e4be5b in an isolated checkout; 35 backend tests and all 310 frontend tests passed. Updated the overview test fixture to identify the state initializer by shape rather than Hook position after the independently committed alias feature added a Hook.
