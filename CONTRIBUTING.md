# 开发与 Windows 分发

首次参与项目，建议先读[开发者导览](docs/DEVELOPERS.md)，了解整体架构、Deep Agents 与 MCP 的分工、主要依赖和贡献入口。

普通使用者参阅 [Windows 部署文档](docs/WINDOWS.md)。开发环境需要 Git、Python 3.11+ 和 Node.js 24。

## 本地开发

```powershell
.\install.cmd -NoLaunch
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
Push-Location frontend
npm.cmd ci
Pop-Location
.\.venv\Scripts\python.exe scripts/run_tests.py --list
# 按改动选择功能，例如文件与 MCP；全量回归使用 --all
.\.venv\Scripts\python.exe scripts/run_tests.py files mcp
# 修改前端产品源码后重新构建
Push-Location frontend
npm.cmd run build
Pop-Location
```

功能分组、跨模块选测和全量回归的适用范围见[测试说明](docs/TESTING.md)。原有 `python -m pytest tests -q` 仍运行完整后端测试。

`frontend/dist` 随仓库分发，目的是让普通使用者无须安装 Node.js。修改前端后必须重新构建并提交构建结果；不要只提交源码而保留旧页面。开发时可运行 `npm.cmd run dev`。普通使用者双击根目录的 `运行.cmd` 完成安装和托盘启动；`start.cmd` 保留为控制台排障入口。

验证部署脚本：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -CheckOnly
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\test-windows.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\test-background.ps1
```

部署脚本测试使用临时目录和模拟命令，覆盖安装重试、成功标记、重复安装、依赖变化和退出码；不修改真实主机、不启动正式服务、不安装系统 Python。

部署测试中的源码打包检查会另外创建不含 pip 的临时 Python 环境，并运行真实的启动器编译、内部参数校验和前端资源清单校验，需要本机具备 Python、Node.js 和 Windows .NET Framework 编译器。它不创建真实桌面快捷方式，也不写入正在使用的数据目录。

默认后端测试不打开原生托盘或浮窗。浮窗菜单实测需显式设置 `IWB_TEST_FLOATING_UI=1`，再运行 `python -m pytest tests/test_floating_context_menu.py -q`；它会打开测试窗口，适合在允许操作桌面的独立验证环境中执行。该测试在子进程中创建和清理 Tk 对象，结束前等待采集线程并在创建线程上回收对象，避免其他测试线程触发 Tcl 崩溃。默认测试仍会运行不创建窗口的 Tcl 生命周期回归用例。

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

GitHub 仓库：[addsubmuldiv/infra-workbench](https://github.com/addsubmuldiv/infra-workbench)。若仓库尚未公开，克隆需要已获访问权限的 GitHub 身份。

```powershell
git clone https://github.com/addsubmuldiv/infra-workbench.git
cd infra-workbench
```

克隆完成后，在资源管理器中打开项目目录，双击 **`运行.cmd`**。

维护者提交并通过检查后推送：

```powershell
git push -u origin main
```

项目采用 [MIT 许可证](LICENSE)。贡献代码和图像资源时，请确认你有权提交，并保留需要的第三方署名与许可说明。

## 版本号维护

发版只需修改根目录 `version.json` 中的 `version`（不带 `v`）。前端开发/构建、演示构建、桌面开发/构建与桌面 CI 会自动同步各清单、锁文件和后台健康接口。发布校验会先确认标签与唯一版本来源一致，再同步。依赖版本与历史文档不会被替换。

提交或创建版本标签前，可主动同步并检查：

```sh
node scripts/sync-version.mjs
node scripts/sync-version.mjs --check
node --test scripts/sync-version.test.mjs desktop/release.test.mjs
```

将派生文件与 `version.json` 一起提交。直接运行 Python 不会执行 Node 同步，因此源码分发前应执行上述命令。已运行后台需重启才能显示新版本。标签仍与版本一致，例如 `v0.2.1`。

内部参数定位见 [内部参数盘点](docs/INTERNAL-PARAMETERS.md)。

## 内部策略维护

内部数字策略的唯一维护入口是带中文注释的 `config/internal-defaults.jsonc`，不是用户配置。修改后运行：

```sh
node scripts/generate-internal-defaults.mjs
node scripts/generate-internal-defaults.mjs --check
node --test scripts/generate-internal-defaults.test.mjs
```

将生成的 Python、TypeScript 和独立探针源码一起提交。前端和桌面构建自动生成，前端测试、CI 和发布检查先拒绝过期产物；源码归档从同一 Git 快照验证，不使用工作区参数。维护者归档需 Node.js，普通源码运行和安装版不需要。修改涉及前端时重建 `frontend/dist`，安装分发需重建桌面安装包。现有进程不热加载这些值。

字段说明、单位、范围和维护规则见 [内部策略维护](docs/INTERNAL-DEFAULTS.md)。容量上限放大需审查 schema 和资源消耗；资源新鲜度、预约判断及更新退出等规则不在普通配置中调整。
