# 远程服务转发 / Remote service forwarding

在本机浏览器打开服务器上的 TensorBoard、Jupyter 等 HTTP 服务时，使用机器卡片的「服务」入口。它只转发端口，不负责安装或启动远端应用。

## 打开一次 TensorBoard

1. 先在目标机器启动自己的 TensorBoard，确认它监听远端 `127.0.0.1:6006`。使用其他端口时，后面填写实际端口。
2. 在这台机器的卡片点击「服务」，选择 TensorBoard 预设，核对远端端口为 `6006`。
3. 本地端口保留 `0`，让后台选择空闲端口；点击「保存规则」。保存后还需点击该规则的「启动」。
4. 看到「转发运行中」后，点击「打开服务」。浏览器应显示远端 TensorBoard 页面；单看隧道状态不能证明应用健康。
5. 使用完点击「停止」。关闭面板不会停止转发；移除机器或退出后台会停止。保存的规则不会自动重新启动。

Jupyter 同样操作，选择 Jupyter 预设并核对实际端口，令牌在 Jupyter 页面输入，工作台不读取令牌。自定义 HTTP 服务选择对应预设并填写实际端口。

## 远程服务与 SSH 隧道怎么选

| 需要 | 建议入口 |
| --- | --- |
| 在本机打开 TensorBoard、Jupyter，自动分配本地端口 | 本页的「服务」面板 |
| 独立管理本地或远程转发、断线重连、启动连接 | [SSH 隧道](SSH-TUNNELS.md)的链条图标 |
| 打开 VS Code 前准备指定隧道 | [VS Code 连接](SSH-TUNNELS.md#从工作台打开-vs-code) |

两个入口的规则分开管理，避免重复占用同一个端口。服务面板只请求本机和远端回环地址 `127.0.0.1`。页面打不开时先核对远端应用和端口，再检查认证或端口绑定错误；见 [故障排查](TROUBLESHOOTING.md#远程服务与文件)。

## English

### Open TensorBoard

Start TensorBoard on the target host at `127.0.0.1:6006` first. Open **Services** on that machine card, select the TensorBoard preset, verify its remote port, and leave local port at `0` to allocate a free port. Click **Save rule**, then **Start** on the saved rule. Once active, click **Open service** and verify that TensorBoard loads. Stop the rule when finished; closing the panel leaves it running.

For Jupyter, select its preset and actual port; enter its token in Jupyter itself. Use **Services** for simple HTTP access with automatic local ports. Use the separate [SSH tunnel manager](SSH-TUNNELS.md#english) for local/remote forwarding, reconnect or startup connection, and VS Code dependencies. The two managers keep separate rules; avoid binding the same port twice.

### Behavior and implementation

Open **Services** on a machine card. Save a named TensorBoard (6006), Jupyter (8888), or custom HTTP rule. Local port 0 selects a free port. Rules persist; tunnels never restart automatically. Start and stop each rule explicitly. Delete stops its listener before removing the rule. All listeners bind only `127.0.0.1` and forward only to remote `127.0.0.1`.

Active means an SSH listener has been established, not that the remote application is healthy. Start the application on the remote machine separately. Enter Jupyter tokens in Jupyter itself; the workbench does not collect them. Close the panel to keep tunnels running; removing the host or shutting down the backend stops them.

Existing verified AsyncSSH password sessions are reused. Otherwise native OpenSSH runs with strict host-key checking, batch authentication, no remote command, and forwarding failure detection. The main connection uses an isolated resolved configuration to exclude inherited forwards. Jump aliases use a separate `ssh -W` child which resolves the original jump configuration and clears forwarding. No passwords are exported and no remote keys are installed.

Shared MCP tools `list_services`, `create_service`, `start_service`, `stop_service`, and `delete_service` reuse the same routes. All require `host_id`; opaque rule IDs are checked against that host. Creation/start descriptions require explicit user requests. Tunnel lifecycle is bound to the backend, not an individual chat.

Validation includes local synthetic SSH servers with real AsyncSSH and installed OpenSSH roundtrips. Production SSH endpoints are not modified during tests.
