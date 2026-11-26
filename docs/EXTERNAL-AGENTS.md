# 本机 CLI 执行引擎

助手的执行引擎可以选择「Claude Code · 本机 CLI」、「OpenCode · 本机 CLI」或「Antigravity · 本机 CLI」。它们使用各自 CLI 的本机登录或 provider 环境变量，不要求填写工作台 API 配置，也不会把工作台保存的 API key 转交给其他服务。

## Antigravity

选择「Antigravity · 本机 CLI」，点击「显示登录命令」，在本机 PowerShell（Windows）或终端（macOS/Linux）运行显示的命令。首次使用请按 `agy acp --login` 的提示，在 Google 页面授权并将授权码填回刚才启动登录的终端。完成后回到工作台发送消息。需要安装官方 `agy` 1.5.16 或更新版本。若工作台找不到 CLI，可给后台设置 `IWB_ANTIGRAVITY_PATH` 指向官方可执行文件。

工作台通过 STDIO 与官方 `agy acp` 通信，Google 登录保存在工作台数据目录下的独立 Antigravity 配置中，由 CLI 管理。每轮传入同一引擎、同一范围内的历史，以及经过工作台校验的 MCP 工具。工作台继续处理机器范围、工具审批和取消操作。CLI 程序是否存在与 Google 账号是否可以使用是两项检查。

参考 [Google ACP 文档](https://antigravity.google/docs/ide/extensions/acp/) 和 [T3 Code 的 Antigravity 接入](https://github.com/pingdotgg/t3code/blob/main/docs/user/providers-antigravity.md)。

## DeepSeek Harness

安装官方 DeepSeek Harness（桌面版随附 CLI，或用 `npm install -g @deepseek-ai/dsh` 安装），在 Harness 中登录 DeepSeek 或在其模型设置中配置 API Key。回到助手选择「DeepSeek Harness · 本机 CLI」。也可以给工作台后台设置 `DEEPSEEK_API_KEY`，优先使用官方 API。若无法自动找到 dsh，可设置 `IWB_DSH_PATH`，指向已安装的官方 CLI。Windows 桌面版可指定其自带的 `dsh.cmd` 路径。

每轮用 `dsh --profile acp` 创建一个独立会话。DSH 自己读取 `DSH_HOME`（默认 `~/.dsh`）中的凭据，工作台不会读取凭据内容。工作台只给 DSH 配置当前会话的 MCP，业务工具仍受机器范围和工作台审批约束。原生 Shell、文件、网络、子 Agent 及插件管理工具不参与该引擎的请求。

参考 [DeepSeek Harness ACP 文档](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/acp/acp/README.md)。

## Claude Code 与 OpenCode

先在本机终端安装并配置对应 CLI。后台检测只表示找到了程序，不代表账号、默认模型或网络可用。找不到程序时可为后台设置 `IWB_CLAUDE_PATH` 或 `IWB_OPENCODE_PATH`。Windows npm 安装只解析已知包中的原生程序或 Claude 的已知 Node 入口，不执行 PowerShell、CMD 或自定义包装脚本。修改路径或登录后可重新打开引擎选择菜单刷新状态。

每轮使用独立临时目录、受保护的配置和新的 CLI 会话。工作台继续传入当前引擎、当前机器范围内的服务端对话历史，最多 60,000 字符；超限按完整消息丢弃最早部分，并向模型说明省略。当前请求单独保留。切换引擎或机器范围后不会导入原来的模型上下文。界面中的旧记录仍可查阅。分支使用同样的服务端范围快照；这些 CLI 不恢复原生隐藏会话，也不支持运行中的「补充指令」。

工具通过每轮随机令牌认证的回环 MCP 连接，复用内置助手的工具校验、机器范围、技能快照及调用记录。Claude 禁用全部内置工具、额外设置来源、斜杠技能、Chrome、hooks 和原生会话持久化，仅加载本轮 MCP；不会跳过权限检查。OpenCode 使用临时 XDG 配置目录、`--pure`，禁用 Claude 配置继承和默认插件，权限先拒绝全部操作，再仅允许工作台 MCP。请求模型前检查其实际合并配置中的 MCP、插件、权限及代理权限。OpenCode 的全局自定义 provider 配置不导入；应使用标准 provider 的本机登录或官方支持的 provider 环境变量。

MCP 令牌不会出现在命令参数、聊天记录或错误日志中。子进程继承系统代理，回环 MCP 绕过代理。输出、等待时间和错误输出都有上限；非零退出、错误事件、缺少完成事件或没有文本都按失败处理。取消会结束本机 CLI 和本轮 MCP；已经启动的远端后台任务仍需显式停止。

## 已验证范围

2026-11-03：本机 Claude Code **2.1.226** 使用既有 OAuth 登录，实际通过合成 MCP 调用了 `list_hosts`、流式返回合成别名，下一轮通过工作台传入的历史正确复述该别名且未再调用工具，并在合成工具等待时取消，确认工具取消及子进程清理。没有连接生产 SSH。

OpenCode 最初未全局安装。为验证在忽略的 `work/opencode-runtime` 中安装了 **1.19.5**，实际验证 `run --format json`、`--pure` 支持及 `debug config` 合并配置隔离。一次 150 秒上限的真实合成工具请求没有返回文本或工具调用，按超时失败并清理；没有验证成功的模型响应、MCP 调用或续聊。不能把安装/配置检查当作账号及模型可用的证明。工作台不会把该临时测试安装当作全局可用程序。

可重复运行 `.venv/Scripts/python.exe scripts/diagnostics/validate-external-agents.py claude`，或在配置好 OpenCode 后将末尾改为 `opencode`。结果写到忽略的 `work/<engine>-live-validation.json`，只含成功标志，不含凭据或会话 ID。脚本只提供合成 MCP，不连接 SSH；会产生少量对应服务的模型请求。

协议参考：[Claude 非交互 CLI](https://code.claude.com/docs/en/headless)、[OpenCode CLI](https://opencode.ai/docs/cli/)、[权限](https://opencode.ai/docs/permissions/)、[配置合并](https://opencode.ai/docs/config/)、[MCP](https://opencode.ai/docs/mcp-servers/)。后续版本如果更改参数或事件，适配器会报告失败，应重新验证后使用。
