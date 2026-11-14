---
name: infra-workbench-ssh
description: 用 Infra Workbench 查机器别名、GPU/NPU 资源或 SSH 登录信息，找到目标后由 Agent 用自己的 SSH 客户端连接和操作。
---

此技能面向真实工作台。演示模式的机器和操作留在演示环境。

1. 已知可用的本机 SSH Host 别名且无需查询工作台资源时，直接用 `ssh <别名>`。否则按任务查询。用户指定机柜、集群或工作台分组时，先用 `list_clusters` 匹配分组名，再用 `get_cluster(cluster_id)` 取得成员 `host_ids`，只从该集合选机。分组名与机器别名分别查找。按别名或硬件定位用 `find_hosts`，按空闲卡和显存筛选用 `search_hosts`，确认指定机器的设备状态用 `get_resources`。仅在确实需要新采样时传 `refresh=true`。目标有歧义时继续缩小范围。
2. 优先用已注册的原生查询工具。如果本会话没有注册，运行此技能目录下的 `scripts/lookup.py`，无需预先注册 MCP。命令中的脚本路径使用本文件所在目录的绝对路径。参数是从标准输入传入的 JSON 对象。示例（macOS/Linux 上可用 `python3`）：

   技能目录指加载 `SKILL.md` 时提供的资源根，不是当前工作区。DSH 用户级安装位于其配置根目录的 `skills/infra-workbench-ssh`；如果加载结果没有给出路径，先确认实际安装位置，不要猜测工作区下存在 `scripts` 目录。

   ```powershell
   '{"name":"用户给出的别名"}' | python "<技能目录>/scripts/lookup.py" find_hosts
   '{"host_id":"查询返回的完整 ID"}' | python "<技能目录>/scripts/lookup.py" get_ssh_info
   ```

   `list_hosts` 可用 `name` 和 `limit` 缩小结果。`search_hosts` 支持 `kind`、`model`、`count`（同一台机器的最少设备数）、`min_free_gib`（每卡）和 `idle`。默认使用本机工作台回环端点，非默认端口可以设置 `IWB_MCP_URL`。
3. 选定目标后只查一次 `get_ssh_info`，同一任务复用连接信息。优先用本机 SSH 别名或返回的 `ssh_argv`，保留端口、跳板和主机密钥校验。Windows 密钥路径和代理依赖只在解析它们的环境有效。后续命令、日志和文件走本机的 `ssh`、`scp` 或 `sftp`。用户要求预约等工作台自身功能时，使用相应的工作台工具。
4. `ssh_argv` 使用 `BatchMode=yes`，适用于密钥或 SSH agent。仅在需要密码且 `auth.ssh_password_available=true` 时取该机器的已保存密码。如果已有能在进程内接收密码并校验主机密钥的 SSH 客户端，可在同一进程里用 `lookup.call("get_ssh_password", {"host_id": ...})` 取 `data.password` 并交给客户端。命令行入口只输出查询数据。密码不进命令参数、日志或回复。没有合适的客户端时，请用户完成交互式认证。跳板可能使用独立凭据。

### 本机直接执行短命令

如果需要复用 Workbench 为目标保存的密码，可以在 Agent 本机运行 `scripts/direct_ssh.py`。它通过本机 Workbench 的完整 `/mcp` 接口在自身进程中读取连接信息及目标密码，再由本机 SSH 客户端直连；不通过训练插件执行文件操作。使用安装了 `asyncssh` 的 Python，确保目标和跳板的主机密钥已由用户验证并写入 `known_hosts`。支持显式的跳板链和本机跳板密钥；嵌套跳板、自定义 ProxyCommand 或需要独立跳板密码时，请改用已配置好的 SSH 客户端或用户交互，不要关闭主机密钥校验。

通过标准输入传入 JSON，不要把密码放入 JSON、命令、环境变量或输出：

```powershell
'{"host_id":"HOST_ID","auth":"saved_password","command":"pwd","timeout":30}' | python "<技能目录>/scripts/direct_ssh.py"
```

`auth` 必须明确为 `key` 或 `saved_password`。`key` 使用 Workbench 给出的本机 OpenSSH 参数；`saved_password` 才会在进程内读取已保存密码。可选 `input` 是远端命令标准输入，`timeout` 为 1–120 秒。输出包含退出码、stdout、stderr 和截断标记；只用于短命令，不用于直接启动需要 Workbench 监控的训练。每路输出最多保留 1 MiB，继续读取并丢弃超出部分；查询大日志应在远端限制范围。无论哪种认证，失败或超时都可能意味着远端操作已发生，先检查远端状态，再决定是否重试；不要自动切换认证方式重放命令。
