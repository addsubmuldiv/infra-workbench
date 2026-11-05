# 助手能力与批准模式

助手输入框的“权限模式”提供三种模式，默认按需批准。无需事先填写目录：直接在消息中描述目标，助手访问时按需请求授权。目录预授权和外部 MCP 放在默认折叠的高级设置中。每轮请求冻结模式和机器范围，切换设置只影响下一轮。新会话不继承旧会话的范围授权；分支恢复原消息的模式和目录，但不复制批准授权。

| 模式 | 行为 |
|---|---|
| 按需批准 | 工作台查询、公开网页搜索和读取自动执行。本机授权目录内的文本读取、写入、编辑自动执行；目录外访问、删除、远端写入和其他变更需要批准。Shell 首次执行需要批准。 |
| 完全访问 | 工具自动执行，不逐项批准。工作目录是任务上下文，不是路径沙箱；机器范围和操作系统账号权限仍有效。 |
| 只读 | 不允许 Shell 或变更工具；不填写目录时可以直接读取本机文件；如在高级设置中填写目录，则本机读取限于这些目录。服务器查询保留已有机器范围限制。外部 MCP 只允许服务明确声明为只读的工具。 |

本机路径必须是绝对路径。local_* 在运行后台的电脑上执行；Windows 使用 cmd.exe，POSIX 使用 /bin/sh。真实服务器文件、命令沿用原有 SSH/MCP 工具。框架 read_file 是虚拟技能、工具长结果和记忆文件，不能把它当成本机文件入口。

批准卡片显示执行目标和完整参数，可允许一次或拒绝。本机读取、写入/编辑和带 cwd 的 Shell 可以授予本对话的目录权限。读取一个文件时，卡片明确显示其所在目录：读取授权同时覆盖目录列表和同目录其他文件；写入授权覆盖该目录的写入和编辑，不包含删除或 Shell。Shell 授权仅覆盖同一执行工具、目录及其子目录，Shell 授权覆盖该目录启动的后续命令，并不限制命令实际能访问的路径。删除、sudo、外部 MCP、远端非 Shell 变更只能逐次批准。更改模式、目录、MCP 配置或机器范围会清除会话授权。只有“完全访问”跳过应用层批准，仍不授予额外系统账号权限。

拒绝不能通过同一工具再次申请或换工具绕过。批准请求绑定会话、运行 ID 和冻结参数，重复或迟到决定返回冲突。取消聊天会使待批准请求失效。等待超过 30 分钟的请求不执行。后台重启后未完成请求记为 interrupted，不会自动执行，用户应核对已有结果后重发任务。

## 工具与边界

- 本机文本文件：目录列表、读取、写入、唯一片段编辑、单文件删除。文本上限 2 MiB，写入/删除须使用读取返回的 revision，新建须使用 missing。读取分页每页最多 6000 字符。
- 本机 Shell：输出有界，超时 1–300 秒。取消/超时尝试终止 Windows 进程树或 POSIX 进程组；主动脱离树的守护进程不保证清理。服务器后台任务仍使用现有任务管理接口，取消聊天不等于取消服务器任务。
- 联网：Bing RSS 搜索，失败后尝试 DuckDuckGo HTML，无需搜索 API Key。免费服务可能超时、限流、返回验证码或低相关性结果，不能承诺覆盖完整。读取公开 HTTP(S) 文本，限制下载大小、超时及重定向；逐跳校验公网 DNS 并固定连接 IP。网页结果属于不可信资料，回答应附来源。暂不支持浏览器登录态、JavaScript 渲染页面和 PDF 正文解析。
- Deep Agents 子 Agent：默认启用 general-purpose，继承同一机器范围、MCP 权限和只读规则，执行步骤共同记录。最多并发 3 个，本轮最多 12 次委派，禁止嵌套委派。原生 CLI 引擎仍通过同一 MCP 使用真实文件、命令和网络工具，不开放额外的独立本机执行通道。
- 外部 MCP：在输入框填写 name HTTP(S)URL，每行一个，最多 3 个 Streamable HTTP 服务、共 100 个工具。不加载本机 stdio 服务，不支持请求头凭据和交互登录。按需批准在连接前询问；配置的本机/内网服务属于用户明确选择的可信服务，和公开网页抓取的公网边界不同。工具逐次经过同一审批层，工具名使用 external_ 前缀，过长名称生成稳定哈希别名。只读声明由外部服务提供，配置前应确认可信。

新本机和联网工具只在绑定了运行权限控制器的助手目录中开放；已有外部 /mcp 客户端不会无声获得本机 Shell 权限。演示模式沿用模拟接口，未知请求不会回落到真实后台。

## 验证与运行

后端修改需要重启才能生效。不要为了加载新功能中断真实终端或后台任务；先确认正在运行的实例。测试使用临时数据目录和模拟模型，不使用真实 SSH 或模型凭据。

English: The assistant supports ask/full/read_only per-run modes, local text files and Shell, public web search/read, Deep Agents delegation and explicitly configured Streamable HTTP MCP services. Approval is bound to immutable arguments and run IDs. Conversation grants are explicit, tool/path-specific, and are not OS sandboxes. Cancellation/restart never executes pending approvals. Free search availability and relevance vary; external MCP readonly hints require trusting the configured server.
