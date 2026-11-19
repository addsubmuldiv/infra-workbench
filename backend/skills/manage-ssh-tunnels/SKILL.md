---
name: manage-ssh-tunnels
description: 用户要求查看 SSH 隧道状态或连接历史，配置、连接、断开、测试隧道，或使用工作台打开远程 VS Code 时使用。
metadata:
  include_tools: find_hosts resolve_target get_ssh_tunnel_status create_ssh_tunnel update_ssh_tunnel start_ssh_tunnel stop_ssh_tunnel delete_ssh_tunnel probe_ssh_tunnel prepare_vscode_remote open_vscode_remote export_host_ssh_config
---

# 管理 SSH 隧道

1. 确认机器 ID，使用 `get_ssh_tunnel_status` 读取当前规则及状态，或以 `section="history"` 分页读取历史。
2. 创建或编辑前核对转发方向和两个端口。`local` 在本机监听并转发到远端回环地址，`remote` 在远端请求回环监听并转发到本机。`update_ssh_tunnel` 提交完整规则，保留用户未要求改动的字段。运行中的规则先取得用户对断开的授权。
3. `start_ssh_tunnel` 返回 `connecting` 时查询实际结果。`probe_ssh_tunnel` 只检查目标 TCP 端口，`reachable=null` 表示无法确认。无需修改规则即可查询。
4. 用户要求打开远程 VS Code 时先调用 `prepare_vscode_remote`。等待前置隧道就绪后，将返回的 `authority` 传给 `open_vscode_remote` 的 `expected_authority`。用户明确要求跳过尚未就绪的隧道时才传 `skip_tunnels=true`。
