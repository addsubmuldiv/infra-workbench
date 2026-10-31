# Deep Agents migration

Goal: Replace the handwritten model/tool loop with Deep Agents while preserving the existing chat API, saved conversations, streaming, cancellation, redaction and selected-host boundaries. The user selected the existing read-only scope.

Architecture: Deep Agents owns iteration, skill discovery and progressive loading, context summarization and virtual context files. A BaseChatModel adapter reuses the existing Responses/Chat transport. ChatTools remains the authority for remote operations. The application stores the framework state alongside its existing conversation record; no tracing service, additional server or external checkpoint service is required.

Branch: `deepagents-harness`. Existing uncommitted streaming changes are the starting point and must be preserved.

Files: `backend/agent_langchain.py` (provider adapter), `backend/agent_runtime.py` (graph, tools, serialized state), `backend/agent_chat.py` (UI/storage lifecycle), `backend/skills/*/SKILL.md` (five workflows), requirements and desktop asset collection, tests and user documentation.

Constraints: No arbitrary shell, credentials, writes or sudo tools. Local framework file tools operate only on an in-memory filesystem populated with bundled skills; remote file tools have distinct names. No implicit subagent delegation. Keep existing UI event formats and fail visibly on unsupported models. Never truncate a tool call into valid execution.

Verification:
- [x] Add regression tests for real Deep Agents skill discovery/read, remote file separation, selected-host enforcement, malformed arguments, budgets and state restoration.
- [x] Replace the loop and retain existing multi-turn, tool-error, cancellation, streaming and redaction tests.
- [x] Pin dependencies and include bundled skills in desktop packaging.
- [x] Run backend and frontend checks, dependency checks and diff checks. Existing Windows temporary SSH-key ACL failure documented separately.
- [x] Validate against the configured real model using an isolated conversation and read-only operations; document actual results and limits in `docs/DEEPAGENTS-VALIDATION.md`.

Review focus: stream interruption must keep partial text without leaking keys; cancellation must not leave executable pending calls; old conversations must migrate without orphan tool calls; narrowed host scope must not execute on an excluded host; virtual skill reads must never reach host disk or SSH.
