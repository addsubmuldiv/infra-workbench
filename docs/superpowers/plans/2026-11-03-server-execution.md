# Server execution implementation plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Allow the assistant to execute authorized server commands, manage background jobs and stop verified processes.

**Architecture:** Add a shared MCP command service over the existing SSH transport. A remote Python supervisor owns bounded output, deadlines and cancellation, so background work can be inspected from a later conversation. Process termination uses a fresh identity check and Linux pidfds.

**Tech Stack:** Python, existing SSHService, Pydantic, MCP, pytest; no new dependency.

**Spec:** User-approved scope in this chat, 2026-11-03: Shell execution, exit status/output, timeout/cancellation/background tasks, process identity checks, existing SSH/sudo, selected-machine scope, explicit authorization.

## Global constraints

- Never run actual user-server mutations during validation.
- Credentials stay in the service and never appear in tool arguments/results.
- Scope is checked before SSH dispatch, including status/cancel operations.
- Default SIGTERM; SIGKILL only when explicitly requested. Never signal PID 1 or process groups through the process tool.
- Existing read-only sudo helper authorization does not imply permission for arbitrary root execution; request sudo explicitly and let the server enforce policy.

## Review focus

- PID reuse between inspection and signal: pidfd plus start-time/UID verification.
- Command output floods: bound stored bytes while continuing to drain both streams.
- SSH disconnect after start: remote job ID allows readback without automatic retries.
- Cancellation and timeout: terminate the command group, record terminal state.
- Host/job handle and path forgery: schema validation and protected remote directories.

### Task 1: Remote execution protocol

**Files:** Create `backend/command_probe.py`, `tests/test_command_probe.py`.
**Interfaces:** `command_main(request)` emits one JSON result; actions start/status/cancel/inspect/signal; supervisor persists owner-only job metadata and bounded output.

- [x] Write tests for successful/nonzero commands, output bounds, timeout, cancellation and PID identity checks; run and observe failure.
- [x] Implement detached supervisor, incremental output reads and verified signal handling.
- [x] Run protocol tests in a local Linux sandbox where available; use portable supervisor tests on Windows and explicitly skip Linux-only cases.

### Task 2: Shared MCP integration

**Files:** Create `backend/command_tools.py`, `tests/test_command_tools.py`; modify `backend/mcp_service.py`, `backend/mcp_server.py`, `backend/ssh.py`.
**Interfaces:** execute_server_command, get_command_job, cancel_command_job, inspect_server_process, signal_server_process; all require host_id.

- [x] Write scope, schema, sudo binding, redaction and catalog tests; observe failure.
- [x] Integrate command service into shared/scoped MCP dispatcher with private credential reuse and explicit sudo flag.
- [x] Run command tests plus existing MCP/chat regressions.

### Task 3: Assistant guidance and delivery

**Files:** Modify `backend/agent_chat.py`, process/file skills, `docs/UNIFIED-MCP.md`; add execution skill.

- [x] Replace outdated blanket prohibitions with task authorization, identity verification and status readback instructions.
- [x] Run relevant backend tests, compile checks and diff review.
- [ ] Check running service and refresh only the application backend if safe; verify live tools without running server mutations.

## Execution decisions

- Implement directly in the current clean worktree; no unsolicited commit/push.
- User already approved the described scope and requested execution; proceed without another plan approval round.
- Fresh review found and fixed process-group cancellation, premature terminal status, Windows sudo argv limit and startup read/poll race. WSL and generated-payload regressions pass.
- Live model verification passed: glm-5.3-flash actually executed printf and inspected/signalled a synthetic WSL sleep process through Deep Agents/MCP, in an isolated database.
- Local backend reload remains pending: automatic approval rejected force-stop/restart; Computer Use did not expose a targetable tray window for normal exit. Do not bypass the rejection; ask user to exit/reopen via tray.
- Other concurrent README.en.md/docs English/image edits appeared during execution; leave them untouched.
