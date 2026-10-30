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

`frontend/dist` 随仓库分发，目的是让普通使用者无须安装 Node.js。修改前端后必须重新构建并提交构建结果；不要只提交源码而保留旧页面。开发时可运行 `npm.cmd run dev`，生产入口仍为根目录 `start.cmd`。

验证部署脚本：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -CheckOnly
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\test-windows.ps1
```

部署脚本测试使用临时目录和模拟命令，覆盖安装重试、成功标记、重复安装、依赖变化和退出码；不修改真实主机、不启动正式服务、不安装系统 Python。

## 代码结构

| 位置 | 职责 |
|---|---|
| `backend/app.py` | 本地 API、主机与轮询、训练前检查、监控规则 |
| `backend/ssh.py` | 本机 OpenSSH、密码会话与免密配置 |
| `backend/core.py` | GPU/NPU 解析和资源判断 |
| `backend/remote_probe.py` | 远端只读采集 CPU、内存、设备、进程和端口 |
| `backend/store.py` | SQLite 中的主机、规则和事件 |
| `backend/desktop.py` | Windows 系统托盘、桌面通知及当前用户登录启动 |
| `backend/assets` | 托盘图标和可编辑 SVG 源文件 |
| `frontend/src` | 页面、主题与浏览器偏好 |
| `install.ps1` / `start.ps1` | Windows 安装及运行入口 |
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
.\install.cmd
```

维护者提交并通过检查后推送：

```powershell
git push -u origin main
```

目前没有选定开源许可证。公开发布前需要确认代码与图像资源的授权；内部试用不要据此推断获得任意再分发许可。
