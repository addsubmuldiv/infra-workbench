# Codex Host Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 工作台承载原生 Codex 执行、审批、Skills、多 Agent 和会话交互。

**Architecture:** 保留官方 App Server 执行循环；共享 MCP 保留服务器校验。独立运行时事件/交互模块把原生事件转换为可持久化 UI 数据，不在 Deep Agents 中仿制 Codex。

**Tech Stack:** Python/FastAPI、Codex App Server 0.167.0 协议、React/TypeScript。

**Spec:** ../specs/2026-11-07-codex-host-design.md

## Global Constraints

- 不读取或复制 CLI 登录凭据，不修改全局配置，不重启生产后台。
- 工作台 MCP 范围不被原生 Shell 绕过后冒充全局约束；UI 明确说明。
- 只读保留读权限并拒绝 Shell/写入；全权限仍受系统与 CLI 策略约束。
- 使用隔离 IWB_DATA、合成 MCP 和临时项目验收，不连接真实 SSH。
- 中英文文案、演示隔离、共享偏好和 frontend/dist 一并更新。

## Review Focus

- 子 Agent 的 thread/turn 事件不得完成根 turn 或污染最终回复。
- 原生提问/审批等待不得阻塞协议读取、取消和并发请求。
- CLI 升级或缺字段必须明确不可用，不回退为无审批全权限。
- 范围/目录/权限/技能/扩展变化不能恢复旧隐藏上下文。
- SSE 重连和旧请求回复不得重复执行或批准新的运行。

### Task 1: Native runtime and protocol

Files: backend/codex_agent.py, backend/codex_host.py (new), tests/test_codex_agent.py.
Interfaces: ChatMessageRequest.codex_options = {cwd,model,effort,multi_agent,enabled_mcp_servers,enabled_plugins}; runtime consumes user turn request. Native items persist in assistant turn.codex_items; questions in turn.codex_questions; capabilities API returns models/skills/extensions/account/capabilities. Runtime interaction handler registers in service.controls with connection/thread_id/turn_id/run_id and interactions object.

- [x] Add tests for config boundaries, read-only native policy, concurrent pending requests, child event isolation, cancellation and scope fingerprints.
- [x] Enable native shell/edit/multi-agent under mapped native permissions; retain no global credential/config mutation.
- [x] Record bounded native items, output and child status; support blocking request answers without blocking transport.
- [x] Verify using scoped pytest cases and review runtime implementation.

### Task 2: API, approvals and discovery

Files: backend/agent_chat.py, backend/codex_interactions.py (new), backend/codex_discovery.py (new), tests/test_codex_host.py (new), scripts/run_tests.py.
Interfaces: GET /api/assistant/codex/capabilities?cwd=; POST chats/{id}/codex-requests/{id} with run_id and decision or answers. Native approvals reuse approvals route and card through codex_ prefix tools; question API binds runtime interaction state. Discovery returns sanitized metadata only, never secrets.

- [x] Test payload validation, stale/duplicate answers and lifecycle cleanup.
- [x] Implement discovery and native request broker; native approve/reject remains run-bound.
- [x] Preserve codex_options in branch drafts; supply engine-specific instructions.
- [x] Run assistant/mcp backend groups and review.

### Task 3: Host UI

Files: frontend/src/CodexHost.tsx (new), frontend/src/AssistantChat.tsx, frontend/src/agentChat.ts, frontend/src/AgentPermissions.tsx, frontend/src/agentChat.css; frontend/tests/codex-host.test.mjs (new).
Interfaces: codex_options above; discovery response {models,skills,mcp_servers,plugins,account,capabilities}; native question answers {questionId:{answers:[string]}}; items {id,type,status,thread_id,data,output,output_truncated}.

- [x] Add directory/model/effort/multi-agent and explicit extension selection backed by shared workspace keys.
- [x] Render native items and question forms, preserve draft and active-run disable behavior.
- [x] Show scope boundary and original CLI capability limitations truthfully, including no-project workspace behavior.
- [x] Test frontend data transforms and compile/build; review.

### Task 4: Live verification and documentation

Files: scripts/validate-codex-host.py (new), docs/CODEX.md, docs/CODEX.en.md (if present), docs/AGENT-PERMISSIONS.md.

- [x] Isolated real CLI smoke for commands, edits, synthetic MCP skills, subagents, approvals/rejection, continuation, questions, steer and cancellation. Record success/failure separately.
- [x] New in-app browser tab/new blank conversation, verify UI without touching production data or system windows.
- [x] Run affected grouped tests, frontend build, diff check, final independent code review and fix findings.
- [x] Update design/plan completion ledger with actual results, limitations and version.

## Execution ledger

- User approved complete design and autonomous implementation/verification, 2026-11-07.
- Ruling: implement in current clean shared workspace on a dedicated codex branch; no automatic push/release. Plan needs no additional approval under the user's explicit instruction to proceed.

- Completed: runtime/API/UI integration, 39 focused backend tests, full regression (1148 backend passed / 15 skipped; 374 frontend passed; 14 helper tests passed), frontend production build and diff check.
- Real CLI 0.167.0 / gpt-6.1-sol: native command/file/diff, parent/child synthetic MCP+Skills, continuation, approval/rejection, Plan question/answer, steer acceptance and cancellation verified. Final receipt: work/codex-host-final-validation.json.
- In-app browser new blank chat: command and final IWB-UI-NATIVE-OK visible, 22247 ms; work/codex-host-ui-validation.json. Test backends stopped; production backend untouched.
- Final reviewer findings fixed and re-reviewed: human wait idle timeout, model-history epochs, resolved branch cwd and copied output sidecars.
- Limits: native browser/computer/image generation not exposed; native search/image-read configured but not separately live-tested; optional plugins/native external MCP and macOS not live-validated. CLI minimum 0.167.0; no push or release.
