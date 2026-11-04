# SSH Tunnels Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Manage persistent, invisible SSH tunnels independently of terminals and VS Code.

**Architecture:** A backend manager owns dedicated SSH connections and reconnect tasks. Native OpenSSH handles key/agent authentication; saved passwords use dedicated AsyncSSH connections with existing credential identity checks. A machine action opens a localized panel; status remains visible when closed.

**Tech Stack:** FastAPI, asyncio, OpenSSH/AsyncSSH, React, TypeScript.

**Spec:** Approved design and mockup in this chat. VS Code launch is excluded.

## Global Constraints
- Bind and target loopback only. Validate fixed ports 1–65535 and rule ownership.
- No terminal, remote commands, remote process killing, or inherited forwarding rules.
- Closing the panel/window does not stop tunnels; backend shutdown does.
- Never store passwords in tunnel rules or expose them through APIs.
- Existing service forwarding remains compatible.

## Review Focus
- Stop during connection/backoff must cancel all work and release resources.
- Remote bind rejection must never report connected or retry indefinitely.
- Repeated start requests must create only one connection.
- Host removal must cancel tunnels and remove rules without leaving a stale host state if credential deletion fails.
- Network failure must update status and reconnect only when requested.

### Task 1: Backend lifecycle and transport
- [x] Add tests in tests/test_ssh_tunnels.py for validation, ownership, real local/remote roundtrips, stop, conflict, reconnect and persistence.
- [x] Run tests and observe missing module failure.
- [x] Add backend/ssh_tunnels.py and backend/tunnel_transport.py with dedicated transports, bounded retries and safe error categories.
- [x] Wire startup/shutdown and host removal in backend/app.py.
- [x] Run tunnel and existing forwarding/password tests.

### Task 2: UI
- [x] Add frontend/src/SSHTunnelPanel.tsx and sshTunnels.css: machine icon, compact panel, saved rule list, direction/ports, connect/disconnect, probe and settings.
- [x] Integrate machine action in main.tsx; disable real operations in demo.
- [x] Build frontend and run existing tests.

### Task 3: Verify and document
- [x] Review cancellation, credential binding, independent ownership and startup behavior.
- [x] Run relevant regressions, document usage and real-server validation limits.

Ruling: Work in the current clean worktree, without automatic commits or service restarts, so the requested change is immediately reviewable.

Validation: 46 relevant backend tests passed; 304 frontend tests passed; frontend production build passed. Real native OpenSSH and AsyncSSH bidirectional roundtrips, bind rejection, explicit-port jump routing and cleanup, cancellation, startup selection and reconnect were tested. Browser checks used an isolated local SSH fixture and verified connect, target probe and connection persistence after panel close. No user's remote servers or VS Code configuration were changed.

Review: independent code review found an explicit-port jump parsing issue, fixed and covered by a real two-hop test. Server-side GatewayPorts can override client loopback binding requests; documented in docs/SSH-TUNNELS.md. Native macOS UI remains unverified.
