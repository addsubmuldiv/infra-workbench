# Deep Agents 迁移与验证

分支：`deepagents-harness`。本次沿用用户选择的现有只读范围。

## 实现

- 用 Deep Agents 0.7.32 的图执行工具循环、技能发现、按需读取及长上下文摘要，移除原有手写循环和最近六轮截取。
- 保留现有 Responses / Chat Completions 传输层、模型设置、系统凭据、聊天 HTTP/SSE、取消和 UI 事件格式。
- 内置五个技能：找卡、进程与服务、服务器文件、训练日志、资源变化。真实服务器的读取与虚拟技能文件读取使用不同工具。
- 复用 ChatTools 的机器范围与参数校验；不提供任意 Shell、修改、删除、提权或子 Agent 工具。虚拟文件系统仅含内置技能和框架生成的上下文，不挂载用户电脑目录。
- 本机 SQLite 同时保存界面对话及框架状态，包括私有摘要状态。旧工具名称会迁移；异常退出和取消不重放未完成操作。关闭 LangSmith 托管追踪。
- 锁定已测试的 Deep Agents、LangChain、LangChain Core 和 LangGraph 版本；桌面打包入口增加技能文件、模块与依赖元数据收集。本轮未重新制作桌面安装包。

## 自动检查

迁移期间先观察到新增用例失败，再完成实现。用例实际运行 Deep Agents 图，模型与 SSH 使用可控替身；并非用另一个假循环替代框架。

覆盖技能发现和读取、虚拟文件访问限制、远端工具 schema、选中机器边界、原参数省略语义、工具调用上限、无效 JSON、取消工具执行及下一轮继续、旧会话迁移，以及长历史摘要和摘要状态恢复。原流式显示、断线重连、脱敏、工具错误、模型协议和桌面自检继续验证。

- 后端全量运行：507 通过、8 跳过、1 失败。失败为此前已有的 `test_password_login_then_provision_and_verify_key[False]`，Windows 临时私钥 ACL 导致 OpenSSH 验证失败，未纳入本次修改。
- 随后修复参数省略与摘要状态恢复细节，迁移专属 14 项用例通过，包含旧会话迁移、工具参数及调用 ID 脱敏、最终回答正常尾部保留；核心会话和流式相关 35 项通过。
- 最终合并运行迁移、会话、流式、两种模型协议、设置及桌面自检相关测试：94 项通过。
- 最终前端 200 项测试通过；TypeScript 与生产构建通过。工作区同时存在其他界面改动，沿用它们，不把它们归为本次 harness 的实现。
- `pip check` 和 `git diff --check` 通过。

独立代码审查发现完成回调沿用流式脱敏可能误删正常尾部字符，已用先失败后通过的测试修复。审查也推动补强工具参数和调用 ID 在执行、保存前的脱敏；两处修复经复查无新增重要问题。

## 实际模型与服务器

使用当前保存的 `glm-5.3-flash` / Responses 设置和系统凭据，在隔离的数据目录创建验证会话。现有后台只提供配置及采样来源，没有重启原后台或修改原数据。只操作一台已有机器，保留机器范围限制。

| 轮次 | 实际行为 | 结果 | 总耗时 |
| --- | --- | --- | --- |
| 1 | 读取找卡技能，执行资源筛选与设备查询 | 完成，工具均成功 | 25.2 秒 |
| 2 | 重新创建会话服务，读取进程/文件技能，真实 SSH 系统检查及 `/etc/os-release` 读取 | 完成，工具均成功 | 23.9 秒 |
| 3 | 恢复会话，读取变化分析技能并查询隔离环境记录 | 完成；环境无历史记录，不补造结果 | 25.9 秒 |
| 4 | 读取训练日志技能，在未指定路径时说明需要的信息 | 完成；没有扫描目录或读取真实训练日志 | 18.1 秒 |

这四轮证明五个技能确实被模型读取，并能调用实际业务工具；没有验证真实训练日志的数值对比，也没有遍历全部服务器。耗时是本次样本，不是性能保证。

另外启动隔离的本地 HTTP 服务，通过真实 HTTP/SSE 客户端验证：

- 完成一轮技能读取与资源查询，17.1 秒结束，首段文字约 14.4 秒到达，收到 53 次文字更新。
- 下一轮要求较长回答，约 4.7 秒收到首段后立即发送取消请求，最终状态为 `cancelled`，已有文字保留。
- 验证服务结束后正常关闭，未替换当前正在运行的旧后台。

本地报告位于忽略目录 `work/deepagents-validation/report.json` 和 `report-http.json`，只保存耗时、字符数和工具状态。隔离数据库中有实际业务返回内容，不应作为分发材料。

## 复验

```powershell
.venv/Scripts/python.exe -m pytest tests/test_deepagents.py tests/test_agent_chat.py tests/test_chat_stream.py tests/test_model_turn.py tests/test_model_stream.py tests/test_agent_api.py tests/test_desktop_runtime.py -q
.venv/Scripts/python.exe -m pip check
git diff --check
```

需要本机已有后台、保存的模型凭据和至少一台在线机器时，可运行以下实际验证；会调用模型 API，并执行上文列出的只读操作：

```powershell
.venv/Scripts/python.exe scripts/validate-deepagents.py
.venv/Scripts/python.exe scripts/validate-deepagents.py --http
```

更新后的正式后台需要重新启动才能加载新依赖与执行层。Mac 实机和冻结后的桌面安装包尚未验证。
