# SSH 隧道 / SSH tunnels

机器卡片的链条图标用于管理独立 SSH 隧道，不会打开终端，也不依赖 VS Code。

## 统一管理

页面顶部的“隧道管理”列出所有在线机器，以及有已保存隧道的机器，不受机器选择、搜索或设备类型筛选影响。至少有一条隧道已连接的机器排在最前面，曾连接成功的排在后面，从未连过的排在最后。升级前保存的配置缺少连接记录，先随曾连接过的机器一起排在中间，下一次连接成功后会记录下来。

列表每两秒刷新状态。可以直接连接或重连已保存的隧道，单条断开，或断开全部运行中的隧道。点击“管理”编辑对应的隧道，或在没有配置的机器上点击“配置隧道”创建第一条。关闭管理窗口不会停止隧道；从托盘退出后台会断开全部隧道并取消重连。

助手可按机器调用只读 MCP 工具 `get_ssh_tunnel_status`。默认读取当前状态，设置 `section="history"` 可查看启用此版本后记录的连接、断开和失败，最新事件在前，每台机器保留最近 100 条。同一次重连过程中连续出现的相同错误合并记录。修改或删除隧道配置后，历史仍保留当时的方向、端口和失败原因。移除机器会清理对应历史。后台被强制结束时可能来不及记录断开事件。

排查远端代理端口时，对照 `direction="remote"` 的 `remote_port`，再用 `ssh_check(check="ports", port=remote_port)` 查看远端监听。工作台记录的是它观察到的连接状态，远端监听是否释放以实时检查为准。端口和进程名相同仍需核对归属。

## 远端 Codex 使用本机代理

1. 点击机器上的链条图标，填写名称，选择“远端访问本机（代理）”。
2. 本机端口填写本机代理正在监听的 TCP 端口，例如 `7890`；远端端口填写给远端程序使用的端口，例如 `18899`。
3. 点击“保存并连接”。后台接受请求后会关闭弹窗，首次连上或最终失败时会在通知中心留下消息，并按现有设置发送桌面或浏览器通知。连接成功后，远端程序可访问 `127.0.0.1:18899`，流量经 SSH 转发到本机 `127.0.0.1:7890`。
4. 远端程序仍需配置对应的代理协议与地址。工作台不修改 Codex、VS Code 或远端环境变量。
5. 移除 VS Code SSH 配置中重复的 `RemoteForward`。旧隧道占用端口时，工作台会报错，不会终止未知远端进程或自动换端口。

“本机访问远端（服务）”则将本机监听端口转发到远端目标端口，可用于访问远端服务。已有的“服务”面板保持原有行为。

## 从工作台打开 VS Code

机器卡片上的 **VS Code** 按钮会调用本机编辑器，以 Remote - SSH 连接该机器。先安装 VS Code 和 Remote - SSH 扩展；工作台会查找 PATH 中的 `code` 命令，Windows 和 macOS 也会检查常用安装位置。

在隧道配置里勾选 **打开 VS Code 前连接此隧道**，然后保存。该选项默认关闭，原有规则保持关闭；连接中的隧道需先断开才能修改配置。它与“软件启动时连接”相互独立。

点击机器上的 VS Code 后，工作台启动该机器所有勾选的隧道，最多等待 60 秒。全部连接后才提交打开请求；已经连接的隧道直接复用。失败或超时会显示“重试”和“仍然打开 VS Code”，后者只跳过隧道等待，仍会核对 SSH 目标是否变化。取消打开不会断开后台维护的隧道。

VS Code Remote - SSH 沿用本机 SSH 密钥和 agent。添加机器时，如果勾选了 **登录后自动配置免密连接** 并且密钥验证成功，工作台会在本机 `~/.ssh/config` 中为这把密钥准备一个专用别名。已有机器使用工作台专用密钥时，点击 **VS Code** 也会补建别名。别名只记录密钥文件路径，已有 SSH 配置条目会保留。

如果无法准备别名，工作台会按原有目标打开 VS Code，由 Remote - SSH 完成认证；密码登录仍会提示输入密码。使用自定义 `remote.SSH.configFile` 的 VS Code 需要能读到 `~/.ssh/config` 中的专用别名。首次连接时 Remote - SSH 可能需要安装或启动远端组件。

打开成功表示本机 CLI 接受了请求，不表示远端认证完成或 Codex 已可用。此版本只打开机器连接，不记忆远端目录。官方 CLI 用法见 [从终端连接远端机器](https://code.visualstudio.com/docs/remote/troubleshooting#_connect-to-a-remote-host-from-the-terminal)。

## 生命周期与状态

- 可保存多条规则；连接期间配置只读，断开后可修改或删除。
- 关闭面板、主窗口或 VS Code 后，托盘后台继续维护连接。彻底退出后台时关闭连接。
- 网络故障后按 2、5、10、30 秒间隔重试，后续保持 30 秒；主动断开会取消连接中和等待重试的任务。
- 开启“断线自动重连”后，远端转发被拒绝时也会按 2、5、10、30 秒的间隔各重试一次，给旧 SSH 会话留出释放端口的时间。端口仍被占用或服务器仍拒绝转发时，隧道会显示连接失败。
- 认证、主机密钥和本机监听端口绑定错误需要修正后手动连接。
- 默认不在软件启动时连接，可对每条规则单独开启。
- “检测目标端口”只检测 TCP 目标是否可连接，不验证代理协议、外网或 Codex 可用性。原生 OpenSSH 的本地转发只报告隧道状态，提示使用本机端口验证远端服务。
- 密码登录的独立连接需要先在机器的 SSH 密码设置中保存密码，凭据沿用系统凭据存储及 SSH 身份绑定检查。临时登录会话不会被隧道复用。
- 免密登录支持已有密钥、SSH agent 和跳板配置。隧道使用专用 SSH 连接，禁用连接复用及继承的转发规则。

客户端只请求 `127.0.0.1` 监听并只转发到 `127.0.0.1`。远端 SSH 服务端最终决定监听行为；例如 OpenSSH 的 `GatewayPorts yes` 可以覆盖请求地址。需要远端严格回环监听时，服务端应采用 `GatewayPorts no` 或 `clientspecified`，并核对实际监听地址。工作台不会修改服务端 SSH 配置。

## English

The page header's **Tunnel manager** shows online machines and machines with saved tunnels, regardless of sidebar selection or filters. Machines with a connected tunnel come first, followed by machines with a previous successful connection, then machines that have never connected. Older saved configurations have no connection history and sort with previously connected machines until a successful connection is recorded.

Status refreshes every two seconds. Connect or reconnect saved tunnels directly from the list, disconnect one tunnel or all active tunnels, and open **Manage** to edit a specific tunnel. Choose **Set up tunnel** to create the first tunnel for a machine. Closing the manager keeps tunnels running. Quitting the backend disconnects them and cancels reconnects.

The read-only MCP tool `get_ssh_tunnel_status` lists current tunnels by machine. Set `section="history"` for up to 100 recorded connection, disconnection, and failure events per machine, newest first. Consecutive identical failures during the same reconnect sequence are recorded once. History starts with this version and preserves the forwarding direction and ports at the time of each event. Abrupt backend termination can leave no disconnect event. Inspect the remote listener separately with `ssh_check(check="ports", port=remote_port)` for remote forwarding and verify its process identity before attributing it to a tunnel.

The machine's **VS Code** button launches local VS Code with Remote - SSH. Enable **Connect before opening VS Code** on each required tunnel and save it. All selected tunnels must connect before launch, with a 60-second wait limit. Failure offers retry or an explicit skip; cancelling leaves backend tunnels alone. The launch target is rechecked even when skipping. Install VS Code and Remote - SSH first. Remote - SSH uses local keys and the SSH agent. When Workbench provisions a dedicated key while adding a machine, it prepares an alias in `~/.ssh/config` that references that key. Opening VS Code for an existing machine with a dedicated key also prepares the alias. If Workbench cannot prepare an alias, it opens the original SSH target and Remote - SSH handles authentication. A custom `remote.SSH.configFile` must include the generated alias. A successful launch confirms that the CLI accepted the request.

Use the chain icon on a machine card to create dedicated SSH tunnels. Remote-to-local mode makes a local proxy available through a fixed remote loopback port; local-to-remote mode exposes a remote service locally. Set the local and remote ports, save, and connect. Configure the remote application's proxy separately and remove duplicate VS Code `RemoteForward` rules.

After the backend accepts a manual connection request, the dialog closes. The first successful connection or final failure appears in the notification center and uses your existing desktop or browser notification settings.

Connections belong to the backend and continue when panels or VS Code close. Quit the backend to disconnect. Optional network reconnect and app-start connection are configured per rule. With reconnect enabled, a rejected remote forward is retried up to four times, with delays of 2, 5, 10, and 30 seconds, to give an old SSH session time to release the port. Authentication, host-key, and local binding errors require manual correction. Password-based hosts need a saved SSH password. Target-port checks test TCP reachability only.

The client requests loopback listening, but the SSH server controls the final bind address. Server configurations such as `GatewayPorts yes` can override it. No server configuration is changed automatically.
