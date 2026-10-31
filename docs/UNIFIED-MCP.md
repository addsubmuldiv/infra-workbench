# 统一 MCP 与业务技能

开发分支：按用户要求在 `main` 完成。模型连接和业务服务保持在本机后台。

## 调用关系

```text
聊天 HTTP/SSE → Deep Agents → MCP SDK 客户端（进程内消息流）
                                       ↓
外部 MCP 客户端 → /mcp（Streamable HTTP）→ 同一能力目录及分发器
                                       ↓
               查询服务 / SSH 探针 / 原有应用接口和数据库
```

进程内消息流执行真实 MCP initialize、tools/list、tools/call；没有另写一个假 MCP 调用函数。它避免后台向自己监听的端口发网络请求。内置连接在服务端绑定本轮机器范围和会话状态，模型不能通过参数扩大范围。外部客户端保留原有本机服务信任边界。

`mcp_operations.py` 只登记明确的业务操作，并从 FastAPI 原有模型生成参数 schema。调用原有应用接口，继续执行其参数校验、并发控制、版本冲突、持久化和通知逻辑。没有开放任意 HTTP 地址、任意 Shell 或动态 Python 执行工具。

## 能力与边界

当前外部目录 55 个工具，内置 Agent 53 个（不提供两个旧 SSH 连接/密码工具）。

| 类别 | 主要 MCP 工具 |
| --- | --- |
| 资源和进程 | list_hosts、search_hosts、get_host、get_resources、search_fleet、ssh_check、read_changes |
| 预约写入 | create_reservation、update_reservation、cancel_reservation；get_workbench_state 查结果 |
| 监控写入 | create_rule、delete_rule |
| 文件 | read_server_directory、read_server_file、search_server_files、file_operation |
| 训练日志 | read_training_log、compare_training_logs、get_log_record、对比配置增删查 |
| 训练前检查 | preflight、refresh_host |
| 终端 | 查看/创建/结束持久会话；交互本身走软件 WebSocket |
| 导入与连接 | connect_host（已有密钥）、导入批次状态/开始/丢弃；表格字节交接给客户端 |
| 文件传输 | 创建上传、进度与取消；下载工具返回 HTTP 交接参数 |
| 技能和设置入口 | list_skills、read_skill、get_workbench_entry；只读邮件、sudo 和密码保存状态 |

凭据输入/保存、模型连接自配置、桌面通知发送回执、聊天自身管理不暴露为模型业务工具。原有六个外部工具兼容保留；内置模型不获得 `get_ssh_info` / `get_ssh_password`，直接复用后台 SSH。MCP 请求体上限 64 KiB，大文件由客户端通过原传输接口发送。

下载的 `handoff_required` 表示尚未下载。创建上传任务也不代表字节已传到服务器。界面和模型不得把交接描述为成功完成。限定机器范围时，无法证明归属的导入批次/旧下载句柄会拒绝访问。

## 技能负责流程

内置九个技能，四个新增流程为：预约与监控、训练日志精确对比、训练前检查、服务器文件操作。它们组合 MCP 工具，适配器不写“先查机器、再预约、再修改”的任务调度逻辑。外部客户端也可通过 list_skills/read_skill 获取相同内容。

例如「帮我约一台有两张空闲 GPU 的机器，每卡至少 40 GiB」：模型读取预约技能，自行查询候选、刷新核对、创建预约并读回。预约不锁卡、不启动训练。用户只要求查询时不自动创建预约。写入中断或超时不等于回滚，需要先读回再决定是否重试。

## 范围和路径保护

- 主机参数在执行前核对；预约、规则、配置、快照和上传句柄检查原记录归属，修改旧对比配置也不能越过机器范围。
- 机器集合、规则、预约和对比配置结果按允许范围返回；旧事件流缺少可靠 host_id 时不返回，改用 read_changes。
- MCP 文件操作和训练日志读取使用远端真实路径凭据检查。复制/移动也检查目录后代，防止将受保护文件移到普通路径后读取。
- 模型只能消费已通过该路径检查的训练快照；UI 缓存需通过 read_training_log 重读。合成演示快照明确标注为演示。
- 保留工具预算、超时、流式脱敏、取消、中断记录及 SQLite 会话恢复。关闭托管追踪。

## 实际验证

使用保存的 GLM 模型设置，在隔离数据库和合成机器上，经真实聊天 HTTP/SSE → Deep Agents → MCP → 原预约接口完成：

| 操作 | 结果 | 本次耗时 |
| --- | --- | --- |
| 读取技能，创建 1 卡预约，持续空闲 120 秒 | 数据库 1 条预约 | 33.6 秒 |
| 修改持续空闲时间为 300 秒 | 同一预约已更新，其他条件保留 | 21.4 秒 |
| 取消并读回 | 数据库 0 条预约 | 12.4 秒 |

全部使用合成机器、email_notify=false，不接触真实预约、不发邮件。另用已有真实服务器完成四轮只读模型验证：资源查询、SSH system、读取 /etc/os-release、资源变化和技能读取；没有修改远端文件。真实 HTTP/SSE 查询完成，取消请求最终状态为 cancelled。

报告在忽略目录 `work/unified-mcp-validation/report.json` 和 `work/deepagents-validation/`，不提交私有数据。耗时只是本次样本。

后端广泛回归：530 项通过、8 项跳过，排除一个此前已存在的 Windows 临时 SSH 私钥 ACL 用例；完整运行也确认该用例仍失败。随后新增的远端错误映射用例及相关定向测试另行通过。前端 200 项测试、TypeScript 与生产构建通过。

复验：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_unified_mcp.py tests/test_mcp.py tests/test_deepagents.py tests/test_agent_chat.py tests/test_chat_stream.py -q
.\.venv\Scripts\python.exe scripts/validate-unified-mcp.py
.\.venv\Scripts\python.exe scripts/validate-deepagents.py
.\.venv\Scripts\python.exe scripts/validate-deepagents.py --http
```

后三条需要本机已保存的模型凭据并产生 API 调用；真实只读服务器验证还需要运行中的原后台及在线机器。桌面冻结安装包和 macOS 实机未重新验证。

用户授权重启后，正式托盘后台已重新启动。实际 MCP 客户端发现 55 个工具和九个技能；内置 Agent 在正式聊天 HTTP/SSE 中调用 get_workbench_state 成功，SQLite 记录 runtime=deepagents、tool_transport=mcp。原有机器、预约和历史对话保留，未更改真实预约或远端文件。本次对话约 12 秒完成。

首次正式验证暴露了完整 /api/state 含大量端口/进程字典导致模型输出超限的问题。get_workbench_state 现返回范围内的机器概要及准确 host_count/reservation_count/rule_count，详细数据仍由专用工具提供。新增大快照回归用例先失败后通过，相关 50 项检查通过；修复后再次重启并完成上面的正式验证。私有计数和验证记录保存在忽略目录 work/restart-validation/。
