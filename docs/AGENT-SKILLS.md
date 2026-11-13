# 给外部 Agent 安装工作台 Skills

仓库根目录的 [`skills/`](../skills/) 提供可单独安装的 Agent Skills。每项 Skill 有一个独立目录，包含 `SKILL.md` 和所需脚本。

| Skill | 用途 |
| --- | --- |
| [infra-workbench-ssh](../skills/infra-workbench-ssh/) | 查询机器分组、GPU/NPU 状态和 SSH 连接信息，选定机器后由 Agent 自己走 SSH。 |

## 安装和使用

从仓库下载或复制整个 `skills/infra-workbench-ssh/` 目录到客户端的 Skills 目录，保留其中的 `scripts/`。按需创建目标目录。更新时用仓库里的新版目录替换旧版。

| 客户端 | 用户级安装目录 | 在新对话中调用 |
| --- | --- | --- |
| [Codex](https://learn.chatgpt.com/docs/build-skills#where-codex-loads-local-skills) | `~/.agents/skills/` | `$infra-workbench-ssh` |
| [Claude Code](https://code.claude.com/docs/en/skills#where-skills-live) | `~/.claude/skills/` | `/infra-workbench-ssh` |
| 其他支持 `SKILL.md` 的 Agent | 客户端指定的 Skills 目录 | 使用客户端的 Skill 选择器或调用方式 |

`~` 指当前用户的主目录，Windows 下通常是 `C:\Users\<用户名>`。例如，Codex 安装后的文件应位于 `~/.agents/skills/infra-workbench-ssh/SKILL.md`。

在运行真实工作台的电脑上启动 Agent，确认它有 Shell 和 SSH 客户端。若 Agent 已接入工作台的 [MCP](MCP.md)，Skill 可以直接用原生查询工具。也可以用随附的 Python 3 脚本访问本机 MCP，无需额外安装 Python 包或注册 MCP。默认地址是 `http://127.0.0.1:8765/mcp`。如使用不同的本机端口，在 Agent 的执行环境中设置 `IWB_MCP_URL`。

例如，调用 Skill 后可以说「在示例机柜里选一台有两张空闲 GPU 的机器，再用 SSH 执行 `hostname` 核对目标」。查询经 MCP 完成，远端命令和文件操作经 Agent 的 SSH 客户端完成。需要使用工作台保存的登录密码时，Agent 需要一个能在进程内接收密码并校验主机密钥的 SSH 客户端。

## English

Copy the entire [`infra-workbench-ssh`](../skills/infra-workbench-ssh/) directory, including `scripts/`, into your client's skills directory. Use `~/.agents/skills/` for Codex or `~/.claude/skills/` for Claude Code. In a new chat, invoke `$infra-workbench-ssh` in Codex or `/infra-workbench-ssh` in Claude Code.

Run the agent on the computer running Infra Workbench. The skill uses native Workbench MCP tools when available. Its bundled lookup script uses the Python 3 standard library and defaults to `http://127.0.0.1:8765/mcp`. Set `IWB_MCP_URL` for a different local endpoint. Once the target is identified, the agent uses its own SSH client for commands and file transfers. Using a saved password requires an SSH client that can accept it in-process and verify the host key.
