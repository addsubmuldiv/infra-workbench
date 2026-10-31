# Unified MCP Implementation Plan

**Goal:** Share application capabilities through MCP, consume them from the embedded Deep Agents client, and describe workflows in skills.

**Architecture:** Keep the six existing MCP tools compatible. Extend a single catalog with existing read probes and typed application operations, deriving JSON schemas from FastAPI rather than duplicating request models. Embedded clients use the official MCP SDK over in-process message streams; external clients use Streamable HTTP. Both use the same dispatcher. Bind scope/state on the server, never in model arguments. Binary transfers and interactive terminal operations return explicit transport handoffs.

**Tech Stack:** Python, FastAPI, MCP SDK 2.3.0, Deep Agents 0.7.32, SQLite.

## Constraints and decisions

- Develop on main as requested. Preserve unrelated untracked frontend outputs.
- Do not expose model/SMTP/SSH credential configuration to the embedded model. Preserve explicit legacy external SSH password access.
- No generic HTTP proxy tool or arbitrary shell. Catalog entries select exact existing operations.
- Preserve machine scope, omission semantics, validation, bounded outputs, cancellation and persistence.
- Mutation tools describe their effects; use only when explicitly requested. Live validation performs reads only. Binary handoffs do not claim completion.
- Skills contain business sequences; transport adapters contain no task planners.

## Tasks

- [x] Add failing integration tests for expanded discovery, scoped calls, errors and real SDK round trips.
- [x] Implement shared catalog/dispatcher, reuse application endpoints, retain legacy tools and document transport-only capabilities.
- [x] Replace Deep Agents direct dispatch with SDK discovery/calls; test cancellation, restart and scope isolation.
- [x] Expand skills for log comparisons, preflight, reservations/rules and file operations.
- [x] Run targeted and broader checks, real model/SSH HTTP/SSE validation, inspect the final diff and record limits.

## Review focus

- Selected-machine scope must apply before querying, refreshing or returning global collections.
- Snapshot/config/transfer IDs must not bypass machine scope.
- Tool errors remain MCP errors and must not be interpreted as successful execution.
- Cancellation must stop the server task and close the in-process SDK session without replay.
- Binary and interactive operations need truthful handoffs, not fake JSON completion.

## Execution record

- Added shared catalog and official SDK memory-stream client; 55 external tools, 53 embedded (legacy connection/password tools omitted), nine skills.
- First new integration run failed because the old ChatTools had no MCP session. Implemented protocol transport and schema discovery; retained old ChatTools only as server-side probe primitives.
- Preserved caller exceptions across SDK task-group exit so cancellation, tool budgets and readable provider errors retain their original behavior.
- Independent review reproduced old-config ownership takeover and protected-path laundering. Added failing tests, then fixed original-record scope and shared remote realpath/tree policy. Follow-up review verified symlinks and directory copy/move denial.
- Added model-safe snapshot provenance after review reproduced a UI-cache credential bypass. Added a failing test and verified the fix.
- Added a failing remote-probe error test; corrected envelope mapping so a probe error remains an MCP tool error.
- Real model via HTTP/SSE created, edited and cancelled an isolated synthetic reservation; SQLite counts 1/1/0. Real SSH reads and HTTP/SSE cancellation also passed.
- Broad backend check: 530 passed, 8 skipped, one deselected existing Windows temporary SSH key ACL test (also observed failing in the full run). New probe-error test and final targeted suite checked separately.
- Frontend 200 tests and production build passed; pip check and diff whitespace check passed.
- No production restart, remote writes, real reservations or mail delivery performed. See docs/UNIFIED-MCP.md for exact scope and reproduction.
