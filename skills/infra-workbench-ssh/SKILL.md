---
name: infra-workbench-ssh
description: 用 Infra Workbench 查机器和 SSH 连接信息，再由 Agent 使用自己的 SSH 客户端操作服务器。
---

# 查询机器并使用 SSH

## 1. 判断目标

- **何时执行**：用户要求访问服务器，或需要查询机器、设备、集群与 SSH 连接信息。
- **操作**：已知可用本机 SSH Host 别名且无需查询资源时，可直接使用 `ssh <别名>`。否则先查询 Workbench。
- **结果**：明确目标是单机还是集群。
- **失败处理**：别名或目标有歧义时继续缩小范围，不猜测。

## 2. 查询 Workbench

- **工具**：优先使用会话中已注册的原生查询工具；如果没有，使用技能目录的 `scripts/lookup.py`。通过标准输入传 JSON，示例：

  ```powershell
  '{"name":"用户给出的别名"}' | python "<技能目录>/scripts/lookup.py" find_hosts
  '{"host_id":"查询返回的完整 ID"}' | python "<技能目录>/scripts/lookup.py" get_ssh_info
  ```

- **输入**：已知别名用 `find_hosts`；设备条件可用 `search_hosts`；检查特定机器用 `get_resources`。用户指定集群或机柜时先用 `list_clusters` 和 `get_cluster` 获取成员，只从成员中选机。
- **结果**：获得完整 `host_id`、资源采样时间和所选机器。
- **失败处理**：采样缺失或过期时保留未知；资源查询不代表预约。仅在确需新采样时使用 `refresh=true`。

技能目录是加载 `SKILL.md` 时提供的资源根，不是当前工作区。DSH 用户级安装位于其配置根目录的 `skills/infra-workbench-ssh`。默认使用本机 Workbench 回环端点；非默认端口可设置 `IWB_MCP_URL`。

## 3. 使用本机 SSH 连接

- **何时执行**：已确定目标，需要读取、准备或运行远端内容。
- **操作**：查询一次 `get_ssh_info`，同一任务复用信息。优先使用本机 SSH 别名或返回的 `ssh_argv`，保留端口、跳板和主机密钥校验；文件操作使用本机 SSH、SCP 或 SFTP。
- **结果**：Agent 自身与目标机器建立连接，再执行用户授权的操作。Workbench 返回的连接描述不代表已经成功连接。
- **失败处理**：主机密钥未验证时先由用户完成验证；不关闭校验。Windows 路径和代理依赖只在解析它们的环境有效。

`ssh_argv` 使用 `BatchMode=yes`，适用于密钥或 SSH agent。只有目标需要密码且 `auth.ssh_password_available=true` 时，才在合适的 SSH 客户端进程内调用 `lookup.call("get_ssh_password", {"host_id": ...})` 并直接交给客户端。不要将密码放入命令参数、环境变量、日志或回复。跳板可能需要独立认证；没有合适客户端时请用户完成交互式认证。

## 4. 可选：使用本机辅助脚本

- **何时执行**：需要复用 Workbench 保存的目标密码，且本机 Python 安装了 `asyncssh`。
- **工具和输入**：运行 `scripts/direct_ssh.py`，在标准输入中传入 `host_id`、`auth`、`command`，可选 `input` 和 `timeout`。例如：

  ```powershell
  '{"host_id":"HOST_ID","auth":"saved_password","command":"pwd","timeout":30}' | python "<技能目录>/scripts/direct_ssh.py"
  ```

  PowerShell 中遇到引号较多的命令时，先用哈希表生成 JSON，避免手工拼接 JSON 引号。例如：

  ```powershell
  $sshRequest = @{ host_id = 'HOST_ID'; auth = 'saved_password'; command = 'cd /tmp && cat train.py config.json'; timeout = 30 }
  $sshRequest | ConvertTo-Json -Compress | python "<技能目录>/scripts/direct_ssh.py"
  ```

  PowerShell 的 here-string 起始标记后必须换行，不能把正文直接接在 `@'` 后面；单引号字符串内部的单引号需要写成两个单引号。涉及复杂脚本时先检查本地命令语法，再执行有副作用的远端操作。

- **结果**：脚本在本机发起 SSH，输出退出码、stdout、stderr 和截断标记。`auth` 必须为 `key` 或 `saved_password`；只有后者读取已保存密码。`timeout` 为 1–120 秒，每路输出最多保留 1 MiB。
- **失败处理**：需要已验证的 `known_hosts`。嵌套跳板、自定义 ProxyCommand 或独立跳板密码不由密码模式自动处理；改用已配置的 SSH 客户端或用户交互。失败或超时可能意味着远端操作已经发生，先检查状态，不自动切换认证方式重放。

## 5. 启动并登记训练

- **何时执行**：用户已授权启动训练并希望工作台跟踪时。
- **操作**：加载 `workbench-training`，先使用 Agent 自身 SSH 启动，再采集每个实际节点的进程身份并调用 `iwb_register_training`。
- **结果**：工作台记录实际机器、命令、脚本、配置和日志；按训练技能核对状态和展示。
- **失败处理**：登记失败、启动回执丢失或身份无法确认时保留已有证据和未知状态，不要仅为登记而重新启动。`direct_ssh.py` 是可选客户端，不是必需的启动器。
