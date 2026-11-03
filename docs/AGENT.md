# Agent 模型接口

在「设置 → Agent 模型接口」配置工作台内置 AI 功能要调用的模型服务。模型接口负责调用模型；MCP 统一提供工作台能力，内置 Deep Agents 和外部客户端共用。

模块提供配置、模型列表获取和真实文本连接测试。左侧「AI 助手」已接入跨机器查找和资源变化摘要，复用现有采集，不需要配置项目路径。模型只在主动查找或生成摘要时调用。

## 配置与测试

1. 填写服务商提供的 API URL，例如 `https://api.example.com/v1`。OpenAI 官方地址为 `https://api.openai.com/v1`。
2. 选择协议：默认「自动兼容」，先使用 Responses，路由不支持时尝试 Chat Completions；也可明确指定其中一种。
3. 填写 API key。无需认证的本地模型服务可以留空。
4. 输入模型 ID，或点击「获取模型」读取该地址的模型列表。列表使用当前表单，获取成功不会自动保存 URL 或 key；不支持列表查询的服务可以手动输入。
5. 点击「保存 Agent 设置」，再点击「测试连接」。测试发送一条固定的简短消息，显示实际使用的协议、模型、耗时及回复预览，可能产生少量 API 费用。

支持粘贴完整的 `/responses` 或 `/chat/completions` URL，保存时移除末尾端点并保留原网关路径。例如 `https://gateway.example/custom/v1/responses` 的基础地址为 `https://gateway.example/custom/v1`。不会擅自追加 `/v1`，请保留服务商要求的路径。

仅有 HTTP 200 不算测试成功，必须解析到模型返回的非空文本。认证失败、权限不足、限流、服务端错误、无文本及未完成的 Responses 响应都会明确失败，不自动切换协议重试。自动兼容仅在 Responses 返回 404、405 或 501，且不是已识别的模型不存在错误时尝试 Chat Completions；自动模式一次测试因此可能请求两个端点。

## API key

- 默认勾选「记住 API key」：Windows 使用系统凭据管理器，macOS 使用钥匙串，独立于 SSH、sudo 和邮件凭据。
- 取消勾选时仅保留到本次后台退出；不支持系统安全存储的环境仅提供这种模式。
- 读取设置不返回 key；key 不写入 SQLite、浏览器存储或项目文件。保存成功后清空输入框，之后留空表示沿用原 key。
- 更换模型或协议可以沿用 key；更换 URL 必须重新填写。若新服务无需认证，先点击「删除 API key」再保存新地址。
- 不自动跟随 HTTP 重定向，避免把 key 转发到其他地址。请直接填写最终 API URL。

## 兼容范围

模型列表使用当前地址的 `GET /models`，与所选的 Responses/Chat Completions 协议无关。支持 OpenAI、DeepSeek、Kimi、MiniMax 和 GLM 标准接口的 `data[].id`，以及 GLM Responses 接口的 `models[].slug`；兼容网关也可返回 `models` 数组中的 `id`、`model` 或 `name`。不会用展示名称替代已提供的模型 ID，也不会擅自更换域名或发送密钥到其他地址。

常用基础地址（请以账号及套餐文档为准）：

| 服务 | 基础地址 |
| --- | --- |
| OpenAI | `https://api.openai.com/v1` |
| GLM Responses | `https://open.bigmodel.cn/api/v1` |
| GLM 标准接口 | `https://open.bigmodel.cn/api/paas/v4` |
| DeepSeek | `https://api.deepseek.com` |
| Kimi | `https://api.moonshot.cn/v1` |
| MiniMax | `https://api.minimax.cn/v1`（旧域名 `https://api.minimaxi.com/v1`） |

获取成功后会显示可选择的模型下拉框，也保留手动输入。列表最多显示 500 个；服务端声明还有后续页面时会提示列表不完整。列表成功不代表账号有权调用每个模型，仍需保存后测试连接。HTTP 200 中的业务错误也会明确报错，不显示为“不支持列表”。未提供列表接口的服务仍需手动填写，不会以固定模型名单冒充实时结果。

参考：[OpenAI 模型列表](https://developers.openai.com/api/reference/resources/models/methods/list)、[DeepSeek 模型列表](https://api-docs.deepseek.com/zh-cn/api/list-models/)、[MiniMax OpenAI SDK](https://platform.minimax.cn/docs/api-reference/text-openai-api)。GLM Responses 的 `models[].slug` 格式已用配置地址实测。

当前支持 Bearer 认证或无认证的 OpenAI Responses 与 Chat Completions 文本接口，可用于实现相应协议的网关和本地服务。不是所有服务商的原生协议都能直接接入；Anthropic 原生 Messages、自定义认证头、Azure 查询参数等尚未实现，可以通过 OpenAI 兼容网关接入。

URL 不接受内嵌账号密码、查询参数或片段。支持 HTTP/HTTPS；密钥会发给填写的服务地址，使用远端服务时应采用 HTTPS。HTTPS 保持证书验证，网络请求沿用后台进程的代理环境变量。

连接测试使用非流式请求，不验证工具调用或多步骤 Agent 执行能力。每个请求默认超时 45 秒，可设置为 5–120 秒；响应上限 1 MiB。连接测试结果仅保留在后台内存，改配置、删除 key 或重启后清除。

## 统一对话

对话执行层使用开源 Deep Agents（当前锁定 0.7.32），在现有 Python 后台内运行。模型接口、API key 和聊天界面沿用原配置，无须运行额外的 Agent 服务。Deep Agents 负责工具循环、技能按需加载和长对话摘要；会话与摘要状态仍保存在本机 SQLite，不启用 LangSmith 云端追踪。

内置技能包括（目录以实时 list_skills 为准）：寻找资源、进程与服务、服务器文件读取、训练日志检查、资源变化、预约与监控、训练精度对比、训练前检查、服务器文件操作。助手先看到技能名称和适用说明，需要时读取完整技能内容；工具记录会显示技能读取过程。技能保存在 `backend/skills/<名称>/SKILL.md`，增加同格式的内置技能后，下一轮对话即可发现。技能只描述流程，实际操作仍须通过软件已有工具；添加 Markdown 不会自动获得新的操作权限。

技能与上下文文件位于内存中的虚拟文件系统，`read_file` 等框架工具不能读取电脑真实文件。服务器文件使用独立的 `read_server_file` / `read_server_directory`，继续执行原有机器范围、路径、分页和凭据检查。业务工具统一通过 MCP 发现和调用，支持按用户要求创建/修改/取消预约、增删监控、文件操作和精确日志对比。不提供任意 Shell、安装或提权；结束持久终端会话必须有明确要求。凭据仍在软件设置中管理。

旧对话可继续使用。长对话由框架生成摘要并保留虚拟历史文件；摘要调用也使用当前模型，因此可能产生额外 API 费用。后台异常退出的本轮会标记中断，下一轮不自动继续执行未完成工具。

打开「AI 助手 → 对话」，直接描述需要了解的机器、资源或文件。沿用设置中的模型和 API key，每轮使用发起时所选的接口配置。提示词和工具说明均为中文。原有「跨机器查找」「资源变化摘要」仍可独立使用。

例如先问「找出我的 vLLM 占卡进程」，再问「检查刚才那台的监听端口」；也可以指定机器和绝对路径，读取配置文件。多个目标无法明确区分时，助手应先澄清。模型生成的文字会陆续显示，工具卡片同步更新目标机器、参数、返回内容、耗时和失败状态，展开可核对原始结果。Responses 和 Chat Completions 均支持流式工具调用，完整参数通过校验后才会执行。

生成中可以点击「取消本轮」，已有文字和已完成的工具记录会保留。断线重连或刷新后会读取当前会话快照；切换会话、关闭页面仅断开显示连接，不等于取消后台任务。阅读前文时不会强制滚回最新文字，回到对话底部后继续跟随。后台会分批保存生成中的文字，不逐字写入数据库；正常完成时保存完整回复。

流式显示需要模型服务实际返回流式事件。如果兼容服务忽略流式请求、仍返回完整 JSON，文本只能在该服务返回后显示。网络中断或生成未完成会保留已有片段并明确标记，不能当作成功完成。

可用工具：

| 工具 | 范围 |
| --- | --- |
| 列出机器、查找资源与进程 | 复用现有采样、条件筛选和 tmux 查询；可按需重新采集 |
| 查看设备资源 | 显存、设备和可见占卡进程，保留采样时间及未知状态 |
| 读取资源变化 | 近 1/6/24/168 小时；限制机器范围时，记录及计数均在该范围内查询 |
| 浏览目录、读取文件 | 当前 SSH 账号；每页最多 100 项，UTF-8 普通文本不超过 1 MiB，每段最多 150 行及 16000 字符 |
| SSH 只读检查 | 系统、进程、TCP 监听端口、磁盘、当前 Python 环境及包元数据、tmux 会话 |

固定 SSH 检查工具只执行预定义探针；此外，共享 MCP 目录提供服务器文件写入、预约和监控变更、持久终端管理，以及 `execute_server_command`、任务查询/取消和进程检查/信号工具。助手可以执行用户授权的远端 Shell、安装或服务管理；这不是只读助手。`sudo=true` 可使用已启用且身份匹配的凭据，否则尝试 `sudo -n`，最终权限由远端 sudoers 决定。不存在覆盖所有写操作的独立人工审批层，请先明确目标、范围和允许的修改。后台强制执行机器范围和参数校验，不能代替用户授权判断。

内置助手复用后台 SSH，不获得 `get_ssh_info` / `get_ssh_password`；外部 MCP 客户端另有显式读取已保存 SSH 密码的工具。文件、命令和进程工具的结果会进入模型上下文。Python 固定检查只代表当前 SSH 的 `python3` 环境。取消对话不会终止已启动的远端命令任务；必须用任务取消工具显式停止，已发生的写入不会回滚。完整行为见 [统一 MCP](UNIFIED-MCP.md)。

默认可访问全部已添加机器。勾选左侧机器范围限制后，查询和写入均由后台强制限制；切换左侧选择不会自动限制对话。上下文包括当前时间、可用机器 ID/别名、用户本轮范围、近期对话、成功解析的查询条件及上次目标。数量、显存等条件可沿用；原始状态过期时仍需重查。

会话及工具片段保存在本机 SQLite，浏览器仅保存当前会话 ID。默认保留最近 7 天、约 30 段会话，单段对话不设固定轮数上限；Deep Agents harness 在上下文较长时自动生成摘要，后续请求使用摘要和近期消息。摘要状态随会话保存，本地可见聊天记录保留。可以新建、切换、删除对话，刷新后可恢复；后台退出后的未完成步骤标记为中断。取消本轮会停止继续调度，不撤销已完成的读取或模型费用，共享采集可能继续完成。

运行限制以当前后台实现为准。工具结果过长时明确标记截断；模型应缩小范围、分页读取或下一轮继续。兼容 Responses 原生 `function_call/function_call_output` 和 Chat Completions 原生 `tool_calls`；服务商除支持文本外还需要支持函数工具调用，连接测试通过本身不能证明这一点。

对话会把允许范围内的机器别名/ID、账号、用户问题、近期对话及实际读取的文件/SSH 结果发送到所配置模型。常见凭据字段、已配置的 API key 和私钥文本会被过滤，常见凭据路径拒绝读取，但自动过滤不能识别所有秘密；不要让模型读取含机密的业务文件。远端文件内容作为不可信数据处理，不能赋予额外执行权限。工具返回与模型结论可分开核对；自然语言结论仍可能出错。

## 跨机器查找

在「AI 助手 → 跨机器查找」输入中文问题，例如「我的 vLLM 在哪台机器」「找 4 个空闲 NPU，每个至少 40 GiB」「我开的 tmux 在哪里」。默认使用当前采样，也可以勾选查询前重新采集。

只把问题和查询结构发给模型，不把机器列表、进程命令或凭据发给模型。模型将问题转成严格校验的 JSON 条件，后台依据真实采样进行匹配，这个独立查找入口不生成或执行远端命令；统一对话可执行授权的命令。结果显示实际解析条件、采样时间和未查清的机器，可以定位机器与设备，或打开对应终端。

进程查询仅覆盖 GPU/NPU 占卡进程，不扫描所有 CPU 进程、Docker、日志或文件。tmux 查询通过现有 SSH 采集执行固定的 `tmux list-sessions`，仅覆盖该 SSH 账号可见的会话；不安装 tmux，不读取会话输出。未安装、权限不足与确实没有会话分别处理。每台机器最多返回 200 个 tmux 会话。

「我的」使用每台机器实际 SSH 登录账号，不使用电脑上的用户名猜测。账号或进程详情未知、采集超过 30 秒、连接失败或刷新未完成时显示限制，不能算作空闲或查询完整。设备数量按同机同类型统计，多芯片 NPU 的设备数不等于物理卡数；资源查询不会锁卡。

## 资源变化摘要

现有轮询会记录占卡进程出现/消失、设备占用变化、采集失败和恢复，不依赖模型。首次采样只建立基线；连接中断、进程状态未知或采样间隔超过 45 秒时，不推断中间任务变化。新模块不会补造启用前的历史。

「AI 助手 → 资源变化摘要」支持最近 1、6、24 小时和 7 天。先查看原始采样事实，再按需生成摘要。发给模型的内容仅包含事实编号、采样时间、机器别名和简短变化描述，不包含完整命令、工作目录、密钥或终端原文。模型提示词与示例均为中文。

每段摘要带有可点击的原始记录编号；引用不存在时拒绝展示。进程消失只能说明采样不再发现该进程，不能据此判断训练成功或退出原因。AI 文本仍需以原始事实为准。无事实时不调用模型。

变化和最小基线存入本地 SQLite，变化最多保留 7 天、10000 条，每次显示最新 100 条，超出范围明确提示。基线只记录 PID、进程名、用户名和设备状态，不保存完整启动命令或工作目录。它与通知中心独立，不额外发送桌面或邮件通知。

对官方 GLM 接口，两个功能会关闭模型思考以减少延迟：Responses 使用 `reasoning.effort=none`，Chat Completions 使用 `thinking.type=disabled`。其他兼容服务不附加这些 GLM 参数。连接测试仍只检查文本通信。

## 开发接口

- `GET /api/settings/agent`：配置和安全存储状态，不包含 key。
- `PUT /api/settings/agent`：保存配置和可选 key；不调用外部模型。
- `DELETE /api/settings/agent/api-key`：删除持久和内存中的 key。
- `POST /api/settings/agent/models`：可传当前表单，也可省略以使用保存的配置；不修改保存的配置。
- `POST /api/settings/agent/test`：测试已保存的配置。
- `GET/POST /api/assistant/chats`：列出或新建会话。
- `GET/DELETE /api/assistant/chats/{id}`：读取或删除本机会话及工具记录。
- `POST /api/assistant/chats/{id}/messages`：开始一轮处理，随后读取会话获取进度。
- `POST /api/assistant/chats/{id}/cancel`：取消本轮后续处理。

修改和外部请求操作沿用本机页面的 `X-IWB` 与 Origin 校验，响应设置 `Cache-Control: no-store`。`backend/agent_api.py` 的文本适配器供后续内置功能复用；工具目录以实时 MCP tools/list 为准。

协议参考：[OpenAI 文本生成](https://developers.openai.com/api/docs/guides/text)、[Chat Completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)。

统一 MCP 架构、能力目录和验证见 [UNIFIED-MCP.md](UNIFIED-MCP.md)。取消不会撤销已完成的写入，结果未知时先查询状态，避免重复预约。

上下文容量优先使用模型设置中的手动值；留空时读取当前接口的模型列表或指定模型元数据，按精确模型 ID 匹配。识别成功缓存一小时，切换接口、模型或密钥后重新识别。框架按容量的 85% 触发摘要。接口没有提供容量时，设置页明确显示“无法自动识别”，暂按 32,000 token 保守处理，可手动填写实际部署容量；不会根据模型名称猜测容量。


## 多套模型接口配置

设置页支持新增、重命名、删除接口配置和设为默认。同一厂商或地址可以保存多套配置，每套的 API key 独立存入系统安全存储。原有单接口配置会自动作为第一套配置使用，原密钥无需重新填写。

新增配置后填写服务商地址、模型 ID、协议和 API key，保存并测试连接。助手顶部的“模型 / 接口”菜单可切换已保存的配置；默认配置在后台重新启动时生效。协议、上下文容量和超时分别保存。不自动在请求失败时切换厂商。

切换后下一条消息使用新配置。正在运行的回复（包括工具调用和上下文压缩）仍沿用发起时的接口和密钥。每条新回复记录实际模型名称。已有对话可以继续，下一轮按新模型容量处理上下文。

配置是工作台全局设置。多个窗口切换时会在窗口重新获得焦点后刷新；陈旧表单的保存、连接测试、密钥删除和聊天发送会检查配置 ID，避免误操作另一套配置。编辑内容尚未保存时先保存，或点击重新加载放弃修改。


## DeepSeek Responses

DeepSeek profile: `https://api.deepseek.com`, protocol `responses`, model `deepseek-flash` (or `deepseek-v4-pro`), timeout 120 seconds. Each API profile keeps its own credential.

DeepSeek Responses is stateless. The workbench resends history and paired function calls/results; it does not rely on `previous_response_id`. The adapter preserves returned plain-text reasoning across tool follow-ups, including framework checkpoints. For the official DeepSeek endpoint, Responses uses `reasoning.effort=high` and a 16,384-token per-call output budget (including reasoning), rather than the generic 2,400-token budget. This is a workbench limit, not the provider maximum.

Context capacity remains metadata-driven: current `/models` returns `context_window=1048576` for both models, separately from `max_output_tokens=393216`. Manual overrides take priority. At 85%, the compression trigger is 891,289 tokens. Unknown models without capacity metadata retain the conservative fallback.

Sources checked 2026-11-01: https://api-docs.deepseek.com/zh-cn/guides/responses_api/ and https://api-docs.deepseek.com/zh-cn/quick_start/pricing/ . Live Responses streaming/function-call follow-up and `/models` capacity were verified with the configured DeepSeek credential.
