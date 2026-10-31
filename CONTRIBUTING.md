# 开发与 Windows 分发

普通使用者参阅 [Windows 部署文档](docs/WINDOWS.md)。开发环境需要 Git、Python 3.11+ 和 Node.js 24。

## 本地开发

```powershell
.\install.cmd -NoLaunch
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest tests -q
Push-Location frontend
npm.cmd ci
npm.cmd test
npm.cmd run build
Pop-Location
```

`frontend/dist` 随仓库分发，目的是让普通使用者无须安装 Node.js。修改前端后必须重新构建并提交构建结果；不要只提交源码而保留旧页面。开发时可运行 `npm.cmd run dev`。普通使用者双击根目录的 `运行.cmd` 完成安装和托盘启动；`start.cmd` 保留为控制台排障入口。

验证部署脚本：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -CheckOnly
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\test-windows.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\test-background.ps1
```

部署脚本测试使用临时目录和模拟命令，覆盖安装重试、成功标记、重复安装、依赖变化和退出码；不修改真实主机、不启动正式服务、不安装系统 Python。

## 代码结构

| 位置 | 职责 |
|---|---|
| `backend/app.py` | 本地 API、主机与轮询、训练前检查、监控规则 |
| `backend/ssh.py` | 本机 OpenSSH、密码会话与免密配置 |
| `backend/agent_tools.py` / `agent_schema.py` | 六个 MCP 工具的统一说明、参数/schema、默认值、示例与恢复动作 |
| `backend/agent_service.py` / `agent_query.py` / `connection_info.py` | 共用查询、有界刷新、资源筛选与 SSH 连接描述 |
| `backend/ssh_passwords.py` | 身份绑定的可选 SSH 密码存储，与 sudo/邮件分开 |
| `backend/mcp_server.py` | 官方 SDK Streamable HTTP 适配与现有后台生命周期集成 |
| `backend/agent_api.py` | 内置模型接口配置、独立凭据、Responses/Chat Completions 适配和连接测试 |
| `backend/agent_runtime.py` / `agent_langchain.py` | Deep Agents 图、模型适配、虚拟技能、工具记录及框架状态保存；不自行维护模型/工具循环 |
| `backend/skills/*/SKILL.md` | 只读业务技能；下一轮对话发现更新，不加载用户目录中的未知技能 |
| `backend/infra_assistant.py` / `resource_history.py` | 中文只读查询条件、确定性跨机匹配、有界变化记录及带引用的 AI 摘要 |
| `backend/core.py` | GPU/NPU 解析和资源判断 |
| `backend/remote_probe.py` | 远端只读采集 CPU、内存、设备、进程和端口 |
| `backend/store.py` | SQLite 中的主机、规则和事件 |
| `backend/desktop.py` | Windows 系统托盘、桌面通知及当前用户登录启动 |
| `backend/assets` | 托盘图标和可编辑 SVG 源文件 |
| `frontend/src` | 页面、主题与浏览器偏好 |
| `install.ps1` / `start.ps1` | Windows 安装及运行入口 |
| `运行.cmd` | 双击后自动安装并启动托盘，后续使用同一入口 |
| `background.cmd` / `background.ps1` | Windows 托盘后台运行入口 |
| `scripts/windows-common.ps1` | 安装、启动共用环境检查 |

sudo 权限由使用者按机器自行启用；安装和后台启动入口不会自动开启任何机器的 sudo，也不会自动启用登录启动。

## 提交与分享

提交前检查：

```powershell
git status --short
git diff --check
git diff --cached --stat
```

`.gitignore` 排除 `data`、虚拟环境、node_modules、数据库、常见密钥、环境文件、日志及本机验证记录。不要用 `git add -f` 绕过这些规则。截图、真实日志和测试样例也需要检查是否包含账号、主机信息或凭据。

提交验证通过的代码后，在项目根目录运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\release-windows.ps1
```

脚本从 **HEAD 已提交内容**生成 `release/infra-workbench-windows.zip`，包含源码、前端构建、文档和安装入口；不会打包工作目录中的私人数据。分发前仍应在另一台 Windows 机器上做首次安装验证。

## 远程仓库

GitHub 仓库：[addsubmuldiv/infra-workbench](https://github.com/addsubmuldiv/infra-workbench)。当前按私有仓库分发，克隆需要已获访问权限的 GitHub 身份。

```powershell
git clone https://github.com/addsubmuldiv/infra-workbench.git
cd infra-workbench
```

克隆完成后，在资源管理器中打开项目目录，双击 **`运行.cmd`**。

维护者提交并通过检查后推送：

```powershell
git push -u origin main
```

目前没有选定开源许可证。公开发布前需要确认代码与图像资源的授权；内部试用不要据此推断获得任意再分发许可。
