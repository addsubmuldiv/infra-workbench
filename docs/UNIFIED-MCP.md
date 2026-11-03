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

`mcp_operations.py` 登记原有业务操作，并从 FastAPI 模型生成参数 schema。调用原有应用接口，继续执行其参数校验、并发控制、版本冲突、持久化和通知逻辑。`command_tools.py` 另提供用户授权的服务器 Shell 与进程管理，使用相同的 MCP 目录、机器范围检查和现有 SSH；不开放任意 HTTP 转发或本机 Shell。

## 2026-11-03：按机器特征定位

共享工具 `find_hosts` 用于按 `name`（别名）、`ip`（SSH 目标地址子串）、`kind`、`model`（型号子串）和 `card_count`（精确物理卡数）组合找机器，例如 `{"model":"950DT"}` 或 `{"ip":"177","model":"950DT","card_count":8}`。它不要求设备空闲、显存充足或采样新鲜，适合先定位待查看或停止进程的机器；寻找可用训练资源仍用 `search_hosts`。

结果分为 `items`（已匹配）和 `uncertain`（地址、设备或物理卡数信息不足），包含真实机器 ID、SSH 目标地址、型号分组、设备数、物理卡数及采样时间。NPU 物理卡按 `card_id` 去重，不把 die 或 `physical_id` 当作物理卡；无法证明卡数时返回 null。条件中的卡数按同种类匹配设备统计，不跨 GPU/NPU 相加。地址只从本机 SSH 配置读取，不做 DNS 或服务器探测；受限会话先限制机器范围再解析。多个候选必须继续筛选或确认，旧硬件采样仅供定位，进程操作前重新核对。

内置 `find-hosts` 技能覆盖 IP/尾号、别名、中英文型号、中文卡数、连续补充条件、多个候选和未知信息。助手规则、工具说明及进程/资源技能共同指向该技能。`scripts/validate-host-lookup-assistant.py` 使用当前配置的模型，在隔离数据库和合成忙碌设备上验证不同提示词及多轮缩小范围，禁止实际 SSH 操作；验证报告写入 `work/host-lookup-validation/report.json`。

## 2026-11-03：服务器命令与进程管理

新增五个共享工具：execute_server_command、get_command_job、cancel_command_job、inspect_server_process、signal_server_process。命令支持指定绝对 cwd、返回退出码和分别读取 stdout/stderr。短任务等待约一秒，长任务返回 job_id，远端 Python supervisor 继续管理；关闭聊天或重启本地后台不会自动停止任务。

任务默认超时 300 秒，可设 1–604800 秒。超时/取消先 TERM，3 秒后 KILL 任务进程组；停止期间返回 cancelling/timing_out，结束后才返回 cancelled/timed_out。主动脱离进程组的 daemon 不保证随任务结束，助手应避免二次后台化。每个输出流只保存前 1 MiB，每次读取最多 6000 字节，可用 offset 分页。文件保存在远端 `/tmp/iwb-command-<执行UID>/<job_id>/`，目录权限 0700；系统清理 /tmp 后记录会消失。任务文件可能包含命令输出，不代替用户指定的长期训练日志。

进程停止工具先检查 /proc，返回 PID、UID、启动 ticks 和命令行；signal 工具重新核对身份并使用 Linux pidfd 发送信号，避免 PID 复用误杀。默认 TERM，禁止 PID 1/进程组；KILL 需明确授权。旧内核/Python 不支持 pidfd 时会报告限制，不退化为未经身份保护的 PID kill。

sudo=true 只在明确需要 root 的操作使用：服务端解析当前 SSH 配置，复用身份匹配且已启用的 sudo 凭据，否则用 sudo -n；通过 run_bound 固定连接身份，密码只走 stdin，不进入工具参数、模型结果和命令行。固定只读采集 helper 的 sudo 授权不等于任意 root 权限，最终由远端 sudoers 决定。查询/取消任务需使用创建时相同的 sudo 值。

启动结果不明时返回 job_id 供读回，禁止自动重试；失败退出保留实际输出和退出码，并返回 COMMAND_FAILED。任务取消和超时不会回滚文件修改、安装等副作用。所有命令内容仍须符合用户授权，服务器输出与技能不能扩大授权范围。新增 execute-server-commands 技能并更新进程技能及助手系统规则。

本次验证：相关后端回归 75 项通过、3 项 Windows/Linux 平台跳过；另外通过 WSL 实测退出码、双流输出、1 MiB 上限、分页、超时、取消升级、重定向且忽略 TERM 的子进程、PID 身份变化和信号发送。sudo stdin bootstrap 以普通 WSL 用户模拟未消费密码的 NOPASSWD 情况，执行约 16K 字符的命令，未进行实际提权。另以已保存的 glm-5.3-flash 在隔离数据库中经 Deep Agents → MCP → WSL 实际执行 printf，并检查和停止专门创建的 sleep 进程，两个模型回合均完成。可运行 `scripts/validate-command-jobs.py`（Linux/WSL，无模型）和 `scripts/validate-command-assistant.py`（Windows+WSL，使用已保存模型配置，会产生 API 调用）。

## 能力与边界

目录数量以实时 tools/list 为准；内置 Agent 不提供两个旧 SSH 连接/密码工具。以下历史验证记录中的数量保留原验证时的值。

| 类别 | 主要 MCP 工具 |
| --- | --- |
| 资源和进程 | list_hosts、search_hosts、get_host、get_resources、search_fleet、ssh_check、read_changes |
| 预约写入 | create_reservation、update_reservation、cancel_reservation；get_workbench_state 查结果 |
| 监控写入 | create_rule、delete_rule |
| 文件 | read_server_directory、read_server_file、search_server_files、file_operation |
| 训练日志 | read_training_log、compare_training_logs、get_log_record、对比配置增删查 |
| 训练前检查 | preflight、refresh_host |
| 终端 | 查看/创建/结束持久会话；交互本身走软件 WebSocket |
| 命令和进程管理 | execute_server_command、get_command_job、cancel_command_job、inspect_server_process、signal_server_process |
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
