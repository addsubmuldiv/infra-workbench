# Deep Agents 原生能力接入

本项目使用已安装的 Deep Agents 0.7.32，由 `backend/agent_runtime.py` 创建图，`backend/agent_langchain.py` 把 LangChain 消息和工具转换为现有模型接口格式。能力审计依据为该版本的 `deepagents/graph.py`、`middleware/skills.py`、`middleware/filesystem.py`、`middleware/_prompt_caching.py` 以及 LangChain 的 `agents/middleware/todo.py`。

| 能力 / Capability | 接入方式及边界 / Integration and limits |
| --- | --- |
| 技能按需加载 / Progressive skill disclosure | `SkillsMiddleware` 索引业务技能和虚拟 MCP 工具技能。初始请求只带技能简介；读取 `SKILL.md` 后，原生 `metadata.include_tools` 激活所需工具。MCP 工具使用 `extras.defer_loading`，模型适配器在激活前不发送 schema。 |
| 计划 / Planning | 使用原生 `TodoListMiddleware` 和 `write_todos`，计划随会话状态保存。原生提示要求仅在复杂多步骤任务中使用，简单查询无需创建计划。计划工具不执行服务器操作。 |
| 历史压缩 / History compaction | 使用原生 summarization middleware，按模型上下文容量触发。摘要、私有压缩状态和虚拟历史文件随 `deep_state` 恢复；可见聊天记录保留。token 数为本地估算，不是供应商计费值。 |
| 大结果卸载 / Large-result offload | 原生 `FilesystemMiddleware` 保留大工具结果卸载，默认阈值为约 20,000 tokens。结果写入会话虚拟文件，可用 `read_file` 分页取回。业务查询分页和输出预算先限制结果，所以普通请求未必触发卸载。 |
| 状态持久化与取消 / State and cancellation | 图运行使用内存 checkpoint；应用将图状态序列化到本地会话数据库，并在后续请求恢复。取消沿现有工具链传播，修复未完成工具消息后再继续，不自动重放中断操作。这不是把运行中的网络连接持久化。 |
| 提示缓存 / Prompt caching | 框架自带供应商专用缓存 middleware，但当前 `WorkbenchChatModel` 不是原生 `ChatAnthropic` 等模型类，这些 middleware 不保证生效。供应商自动前缀缓存取决于接口和模型；未测量命中率或节省比例。 |
| 长期记忆 / Long-term memory | 使用框架 `MemoryMiddleware` 读取应用提供的虚拟记忆文件；记忆持久化和修改范围由应用后端控制。不会因此读取用户目录中的任意 `AGENTS.md`。会话摘要与跨会话记忆是不同数据。 |
| Shell、子代理、任意文件写入 / Shell, subagents, arbitrary writes | 不因框架存在这些功能就全部开放。通用子代理关闭；虚拟文件工具提供查询、读取，以及仅限 `/memories/AGENTS.md` 的写入、编辑和删除；技能文件及其他路径不允许修改。远端操作仍通过现有 MCP 服务，保留权限、机器范围和取消检查。 |

技能披露是减少模型上下文的机制，不是权限控制。即使模型猜到工具名称，也必须由共享后端执行原有参数与机器范围校验。每次模型调用都由框架根据当前技能索引和工具目录重算披露记录；历史记录不应被当成长期授权。

长期记忆由原生 `CompositeBackend` 将 `/memories/` 路由到 `StoreBackend`，SQLite 只负责存储适配。仅 `/memories/AGENTS.md` 可持久化，最多 4096 字符，按模型配置 ID 与精确机器范围隔离。可以告诉助手“记住我偏好表格对比”，也可以要求“忘记保存的偏好”；原生文件工具完成写入或清除，下一轮重新加载。记忆只记录长期偏好和已确认的工作约定，不能把旧采样当作当前事实。服务端拒绝常见凭据和原始日志格式，但这不是能识别任意秘密的通用分类器；提示词同样要求不存储凭据、原始日志和私人文件内容。

English: Native memory persists one bounded note in the application database, isolated by profile and exact host scope. It can be cleared through the assistant; remembered operational facts must be revalidated. Pattern validation is defense in depth, not a universal secret detector.

English: The integration reuses native middleware rather than introducing another planner, skill resolver, or compaction loop. Deferred tool schemas are activated by reading skills. Todo state and graph checkpoints remain local; cancellation does not replay pending server actions. Provider-specific caching is conditional with the generic adapter, and no token-savings benchmark is claimed. Existing MCP validation remains the authorization boundary.

离线验证使用临时数据库和脚本化模型，不连接真实模型或 SSH：

```powershell
.venv\Scripts\python.exe -m pytest tests/test_deepagents.py -q
```

这些测试验证技能披露、会话恢复、摘要恢复、计划持久化、取消和校验边界；构建或单元测试通过不表示真实模型的技能选择质量、缓存命中或远端执行已经验证。

## 上下文预算与新对话

原生摘要中间件使用适配器提供的 token 计数器：未披露的延迟工具 schema 不计入请求预算。模型实际发送前再计算最终消息和已激活工具；超过输入预算时抛出框架原生 `ContextOverflowError`，由原生摘要中间件压缩和重试，避免漏算动态披露的工具。此处没有额外的摘要循环。

容量依次取手动配置、当前服务商的精确型号元数据、已核实的官方型号文档；均不可用时使用 512K（524,288 token）。元数据支持 `/models`、精确型号详情和 `/model/info`，多个部署使用最小明确容量，不把输出上限当作上下文长度。官方文档补充值只对明确记录的官方域名和精确型号生效。OpenAI 标准模型对象没有上下文容量字段，不能依靠 `/models` 保证获取该值。

新对话创建独立会话状态，不继承旧对话消息、摘要和工具披露记录。技能简介、系统提示、当前机器范围，以及该配置和范围已有的长期记忆仍可能进入首轮上下文；因此新对话的输入并非零 token。功能实测应新开 Codex 内置浏览器标签页并创建空白对话，核对首轮是否发生压缩。

English: Deferred schemas are excluded until disclosed. The adapter checks the final bound input and delegates genuine overflow to native summarization. Capacity resolution prefers manual configuration, exact provider metadata, then verified official specifications; unknown models default to 524,288 tokens. New chats have independent history and compaction state, while bounded scoped memory remains separate.

2026-11-05 在 Codex 内置浏览器新标签页、空白对话中，用同一提示“检查可用资源和运行中的服务”实测：54.389 秒、6 次工具调用、5 次回复模型调用、0 次压缩、0 次完全相同的重复工具调用；首轮历史和终端附件均为 0。上一轮记录为 201.586 秒、12 次工具调用、6 次压缩。此次结果覆盖全部 16 台机器的资源采样与占卡进程，未扫描全部监听端口；实时采样和模型响应耗时会波动，单次结果不代表稳定性能保证。

## 并行查询与进程概况

独立只读调用交给框架原生工具节点并行执行。资源和占卡进程查询可以在一个模型轮次发出，各自显式传 scope、view="summary" 和 refresh=true；现有 AgentService.refresh 按机器共享进行中的采集。翻页仍传 refresh=false，不新增缓存有效期，也不把旧采样当作当前空闲证据。

业务技能通过原生 metadata.include_tools 披露 MCP schema。独立工具技能只为没有被已启用业务技能覆盖的工具生成，避免重复目录和说明读取；禁用业务技能后，相应工具仍可通过自动生成的独立入口发现。

进程 summary 按机器、采样时间、用户及详情状态分组。commands 保存不同的进程名称及命令前缀；每组 processes 保留每个 PID 对应的设备 ID 和 command_index，指向 commands 的对应条目，process_count 表示该组进程数；total、offset 和 next_offset 按摘要组计数，total_unit="process_groups"。命令前缀最多 96 字符，command_truncated 表示是否截断，command_is_prefix 明确其显示用途。相同前缀不证明完整命令相同，也不能用于停止进程的身份校验。view="detail" 保留完整命令及 cwd，操作前仍须 inspect_server_process 核对身份。

English: Independent read-only calls use the native parallel tool node; concurrent refreshes share the existing per-host in-flight collection. Process summaries retain every PID/device mapping in display groups with explicit prefix and pagination semantics. Full commands and working directories remain available through detail queries; process actions still require identity verification.

2026-11-05 后续实测在新的 Codex 标签页和空白对话中完成：同一句提示耗时 36.503 秒，3 次模型调用、4 次工具调用（两次技能读取、两次并行 search_fleet），0 次分页续查、压缩和完全重复调用；历史消息和终端附件均为 0。此前 54.389 秒中，模型调用合计 34.381 秒、工具执行墙钟约 13.598 秒；本轮细分记录保存在本地测试报告。结果仍覆盖 16 台机器的资源和占卡进程，不包含完整端口或 CPU 服务扫描，采样及模型延迟会波动。

合并同期 main 查询优化后再次重启，并在另一个新标签页和空白对话复测：44.133 秒，仍为 3 次模型调用、4 次工具调用，0 次分页、压缩和重复调用。前两次模型请求各约 8.4 秒，上次约 4.1 和 5.7 秒；两次最终验证耗时为 36.5–44.1 秒，不能把单次较快结果当作固定延迟保证。
2026-11-05: 内置模型传输已统一为 Responses；大工具结果使用原生 FilesystemMiddleware 完整卸载和虚拟分页读取。原生 memory、skills 和 summarization 保持启用，未另建一套上下文压缩框架。详见 [统一 MCP 文档](UNIFIED-MCP.md#内置助手交互成本整改2026-11-05)。
