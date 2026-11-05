# SSH 隧道 / SSH tunnels

机器卡片的链条图标用于管理独立 SSH 隧道，不会打开终端，也不依赖 VS Code。

## 统一管理

页面顶部的“隧道管理”显示所有机器的隧道，不受机器选择、搜索或设备类型筛选影响。入口数字统计正在连接、已连接和正在重连的隧道。窗口默认列出这些运行中的隧道；勾选“显示全部已保存隧道”可查看未连接和失败的配置。

列表每两秒刷新状态，显示机器、隧道名称、转发方向、端口和连接时长。可单条断开，或断开全部已读取到的运行中隧道；“管理”打开原有配置面板。读取或断开失败会显示对应机器的错误。关闭管理窗口不会停止隧道；从托盘退出后台才会断开全部隧道并取消重连。

## 远端 Codex 使用本机代理

1. 点击机器上的链条图标，填写名称，选择“远端访问本机（代理）”。
2. 本机端口填写本机代理正在监听的 TCP 端口，例如 `7890`；远端端口填写给远端程序使用的端口，例如 `18899`。
3. 点击“保存并连接”。连接成功后，远端程序可访问 `127.0.0.1:18899`，流量经 SSH 转发到本机 `127.0.0.1:7890`。
4. 远端程序仍需配置对应的代理协议与地址。工作台不修改 Codex、VS Code 或远端环境变量。
5. 移除 VS Code SSH 配置中重复的 `RemoteForward`。旧隧道占用端口时，工作台会报错，不会终止未知远端进程或自动换端口。

“本机访问远端（服务）”则将本机监听端口转发到远端目标端口，可用于访问远端服务。已有的“服务”面板保持原有行为。

## 从工作台打开 VS Code

机器卡片上的 **VS Code** 按钮会调用本机编辑器，以 Remote - SSH 连接该机器。先安装 VS Code 和 Remote - SSH 扩展；工作台会查找 PATH 中的 `code` 命令，Windows 和 macOS 也会检查常用安装位置。

在隧道配置里勾选 **打开 VS Code 前连接此隧道**，然后保存。该选项默认关闭，原有规则保持关闭；连接中的隧道需先断开才能修改配置。它与“软件启动时连接”相互独立。

点击机器上的 VS Code 后，工作台启动该机器所有勾选的隧道，最多等待 60 秒。全部连接后才提交打开请求；已经连接的隧道直接复用。失败或超时会显示“重试”和“仍然打开 VS Code”，后者只跳过隧道等待，仍会核对 SSH 目标是否变化。取消打开不会断开后台维护的隧道。

SSH 别名继续由 VS Code 解析，手动机器的账号和端口会带入连接信息。VS Code 独立完成认证，可能提示输入密码；工作台不会传递保存的密码，也不会修改用户 SSH 配置或 VS Code 设置。工作台单独指定的私钥不自动写入 VS Code，若需要，应在对应 SSH 配置中设置 `IdentityFile`。首次连接时 Remote - SSH 可能需要安装或启动远端组件。

打开成功表示本机 CLI 接受了请求，不表示远端认证完成或 Codex 已可用。此版本只打开机器连接，不记忆远端目录。官方 CLI 用法见 [从终端连接远端机器](https://code.visualstudio.com/docs/remote/troubleshooting#_connect-to-a-remote-host-from-the-terminal)。

## 生命周期与状态

- 可保存多条规则；连接期间配置只读，断开后可修改或删除。
- 关闭面板、主窗口或 VS Code 后，托盘后台继续维护连接。彻底退出后台时关闭连接。
- 网络故障后按 2、5、10、30 秒间隔重试，后续保持 30 秒；主动断开会取消连接中和等待重试的任务。
- 认证、主机密钥和端口绑定错误停止重试，需要修正后手动连接。
- 默认不在软件启动时连接，可对每条规则单独开启。
- “检测目标端口”只检测 TCP 目标是否可连接，不验证代理协议、外网或 Codex 可用性。原生 OpenSSH 的本地转发只报告隧道状态，提示使用本机端口验证远端服务。
- 密码登录的独立连接需要先在机器的 SSH 密码设置中保存密码，凭据沿用系统凭据存储及 SSH 身份绑定检查。临时登录会话不会被隧道复用。
- 免密登录支持已有密钥、SSH agent 和跳板配置。隧道使用专用 SSH 连接，禁用连接复用及继承的转发规则。

客户端只请求 `127.0.0.1` 监听并只转发到 `127.0.0.1`。远端 SSH 服务端最终决定监听行为；例如 OpenSSH 的 `GatewayPorts yes` 可以覆盖请求地址。需要远端严格回环监听时，服务端应采用 `GatewayPorts no` 或 `clientspecified`，并核对实际监听地址。工作台不会修改服务端 SSH 配置。

## English

The page header's **Tunnel manager** covers all machines regardless of sidebar selection or filters. It defaults to active tunnels (connecting, connected, or reconnecting); enable **Show all saved tunnels** for stopped and failed rules. Status refreshes every two seconds. Inspect routes and connection duration, disconnect individual or all loaded active tunnels, or open the existing configuration panel. Read and stop failures identify the affected machine. Closing the manager keeps tunnels running; quitting the backend disconnects them and cancels reconnects.

The machine's **VS Code** button launches local VS Code with Remote - SSH. Enable **Connect before opening VS Code** on each required tunnel and save it. All selected tunnels must connect before launch, with a 60-second wait limit. Failure offers retry or an explicit skip; cancelling leaves backend tunnels alone. The launch target is rechecked even when skipping. Install VS Code and Remote - SSH first. Authentication remains in VS Code; saved Workbench passwords, custom private keys and editor settings are not transferred automatically. A successful launch acknowledges CLI dispatch, not remote authentication.

Use the chain icon on a machine card to create dedicated SSH tunnels. Remote-to-local mode makes a local proxy available through a fixed remote loopback port; local-to-remote mode exposes a remote service locally. Set the local and remote ports, save, and connect. Configure the remote application's proxy separately and remove duplicate VS Code `RemoteForward` rules.

Connections belong to the backend and continue when panels or VS Code close. Quit the backend to disconnect. Optional network reconnect and app-start connection are configured per rule. Authentication, host-key, and binding errors require manual correction. Password-based hosts need a saved SSH password. Target-port checks test TCP reachability only.

The client requests loopback listening, but the SSH server controls the final bind address. Server configurations such as `GatewayPorts yes` can override it. No server configuration is changed automatically.
