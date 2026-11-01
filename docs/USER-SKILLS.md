# 用户技能系统

用户技能与内置技能共用一个注册表。用户技能存储在应用数据目录的 workbench.db 中，升级应用代码不覆盖它们。导出格式为标准 Agent Skills ZIP。

## 使用

设置 → 技能：导入 UTF-8 Markdown 或 ZIP，也可以新建并粘贴 SKILL.md。导入先生成草稿，检查内容后校验、安装。草稿会持久保存，可在列表中继续编辑。支持文本参考文件、启停、导出、复制、历史版本回退与卸载。

聊天可以直接要求：

> 把刚才确定的巡检步骤生成并安装成一个技能，名称叫 training-inspection。

Agent 根据实际公开的 MCP schema 编写草稿，通过管理工具校验并安装。只要求讨论或设计时保存草稿；明确要求安装时执行安装。聊天输入框输入 `@` 会弹出技能列表，可按名称或描述搜索，用方向键和 Enter / Tab 选择、Esc 关闭。已选技能显示为可移除标签，每轮最多 16 个，发送成功后清空；未选择时由 Deep Agents 按需发现。

技能创建、更新、停用、回退和卸载从下一轮生效。运行中的一轮固定版本，虚拟文件与 MCP 激活读取共用快照。已读取的历史聊天内容保留，不代表停用技能仍处于启用状态。读取记录代表读取说明，不代表技能步骤执行成功。

## 格式和限制

```markdown
---
name: training-inspection
description: 用户要求检查训练状态或整理训练巡检报告时使用。
metadata:
  workbench-required-tools: list_hosts get_resources
---

先确定机器范围，使用实际可用的工具检查，并区分确认结果和未知部分。
```

技能目录名与 name 一致，支持 references/、assets/ 等相对路径。Markdown 缺少元数据时可导入为草稿并在编辑器补全。ZIP 包含且只包含一个 SKILL.md，不支持一次导入多个技能。

- 上传文件最多 2 MiB；解压后最多 8 MiB、128 个文件，每个最多 1 MiB。
- 拒绝目录穿越、符号链接、特殊文件、加密 ZIP、重复及大小写冲突路径。
- 二进制附件保存和导出时保留，不注入模型虚拟文件。编辑和复制保留原二进制附件。
- 脚本可保存和读取为文本，但不执行；技能不安装 Python 包、MCP 服务或系统软件。
- 工具依赖声明用于检查当前内置 Agent 是否可用，不授予工具或机器权限。
- 格式、引用及依赖检查不等于实际执行验证。业务标准仍由用户和 Agent 明确。

内置技能只读，可复制为新名称。每次用户技能更新创建不可变版本；安装检查草稿修订和原技能版本，冲突不会静默覆盖。卸载后保留数据库中的历史版本用于防止版本号重用，但不再提供读取或回退；需要卸载前导出才能重新导入恢复。

## 接入点

- backend/skill_service.py：事务存储、版本、草稿、包校验与导入导出。
- backend/skill_routes.py：/api/skills HTTP 接口，复用现有本机请求保护。
- backend/mcp_skills.py：草稿与安装管理工具；兼容 read_skill.content。
- backend/mcp_service.py：外部和内置共用服务，内置激活读取固定本轮快照。
- backend/agent_runtime.py：每轮生成虚拟文件、移除旧技能文件、记录读取版本。
- frontend/src/SkillsSettings.tsx：管理页面；AssistantChat.tsx：选择、记录和安装结果。

list_skills/read_skill 在内置会话中读取本轮启用快照；list_managed_skills/inspect_skill 用于管理全部当前技能（包括停用和历史版本）。list_skill_drafts/get_skill_draft 用于继续草稿。这些管理读取不会把技能加入本轮激活快照。

## 验证

```powershell
python -m pytest tests/test_user_skills.py tests/test_skill_integration.py tests/test_deepagents.py tests/test_agent_chat.py tests/test_unified_mcp.py tests/test_mcp.py -q
cd frontend
npm test
npm run build -- --manifest
```

scripts/validate-user-skills.py 从现有 127.0.0.1:8765 读取模型设置，在独立 work/user-skills-live/data 中验证真实模型创建、校验、安装和下一轮读取。复用现有系统凭据机制，不复制机器、对话或打印密钥；会产生两轮模型调用费用。
