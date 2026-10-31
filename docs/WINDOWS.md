# Windows 安装与使用

## 适用环境

- 本机：Windows 10 / 11，Windows PowerShell 5.1 或更高版本，具有写权限的普通目录。
- Python 3.11+，Windows OpenSSH 客户端 `ssh.exe`。
- 首次安装需要访问 Python 包源；Python 缺失时还需要 WinGet 及其下载源。
- 服务器：Linux、Python 3、`nvidia-smi` 或 `npu-smi`；端口检查需要 `ss`。
- 不需要管理员身份，也不需要在远端安装常驻服务。普通用户使用附带的前端构建，无须 Node.js。

不要直接在 ZIP 预览窗口里运行，不要放在 Program Files 等受保护目录，也不要放在多人共享或自动同步的目录：`data` 可能包含专用 SSH 私钥。

## 首次安装

拿到仓库或 ZIP，完整保留目录结构，双击根目录的 **`运行.cmd`**。无需打开终端或手工输入命令，首次安装和后续启动都使用这一个入口。

脚本会依次检查系统和 OpenSSH、寻找 Python、创建 `.venv`、安装 `requirements.txt` 中的固定版本依赖、检查依赖，再启动系统托盘。确认本地服务就绪后打开浏览器，安装窗口自动关闭；程序继续在后台监控。没有 Python 时，CMD 入口会尝试用 WinGet 的 `Python.Python.3.12` 包以当前用户身份安装，不修改全局 PowerShell 执行策略。[WinGet 参数说明](https://learn.microsoft.com/windows/package-manager/winget/install)

安装失败时窗口保留错误。解决网络或依赖问题后，再次运行即可。只有全部依赖检查通过才会写入安装成功标记，已有虚拟环境不代表安装成功。

重复双击会复用完整的安装环境，依赖文件变化时才重新安装依赖。已有托盘和本地服务会被复用，不会启动第二套监控或清空机器、规则。`install.cmd` 是等效的兼容入口。

只安装、不启动：

```powershell
.\install.cmd -NoLaunch
```

只检查环境、不安装软件或启动服务：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -CheckOnly
```

直接调用 PS1 时，自动安装 Python 是可选参数 `-InstallPython`；CMD 入口默认启用。其余安装不提升系统权限。

## 日常启动与连接

双击 **`运行.cmd`**，直接打开界面并保持托盘运行。新启动时只监听 `127.0.0.1:8765`，不要改成 `0.0.0.0` 给其他人共享。

`start.cmd` 用于控制台模式，保持启动窗口运行，按 Ctrl+C 停止服务。

需要在安装后进入控制台，可使用 `install.cmd -Console`；只希望后台启动但暂不打开页面，可使用 `install.cmd -NoBrowser`。这些参数供排障和自动化使用，日常双击即可。

日常仍使用 **`运行.cmd`** 即可；`background.cmd` 是后台启动入口。系统托盘提供桌面通知、打开工作台、通知开关及可选的登录启动。关闭网页后继续监控，无需浏览器通知权限。登录启动默认关闭，在托盘右键菜单中手动勾选。详细说明见 [系统托盘与后台监控](BACKGROUND.md)。

进入“添加机器”，可从 `%USERPROFILE%\.ssh\config` 及 Include 文件导入别名，也可以手动填写。每位同事使用自己的账号、SSH 配置和授权，不要复制你的 `data` 给别人。

新机器首次连接时，先在 Windows 终端执行 `ssh 别名`，或 `ssh -p 端口 用户名@主机`，核对并信任主机指纹，再回到软件连接。指纹变化需先核实原因。

## 更新与修复

更新前先保存文件编辑内容，并妥善结束或保留网页 SSH 终端中的任务。托盘模式从托盘菜单退出并停止后台；控制台模式在原服务窗口按 Ctrl+C。若托盘接入的是已有服务，还需要停止原来的服务入口。

- Git 用户：执行 `git pull --ff-only`，再双击 `运行.cmd`。
- ZIP 用户：解压新版本到新目录。需要迁移机器与规则时，由本人把旧版 `data` 复制到新版相同位置，不覆盖自己的 SSH 配置。不要把它加入分享包。
- 在原目录更新且保留 `data` 时，机器与规则继续保留。浏览器偏好与访问地址、浏览器有关。

强制重新检查并安装依赖：

```powershell
.\install.cmd -Repair -NoLaunch
```

`-Repair` 会重跑 pip 安装与检查，不清空数据；若 Python 被卸载或 `.venv` 本身损坏，停止服务后把 `.venv` 改名备份，再运行安装。不要移动已经创建虚拟环境的整个目录后直接继续使用：虚拟环境依赖原 Python 路径。

## 常见问题

| 现象 | 处理 |
|---|---|
| 找不到 Python / WinGet | 安装 [Python Windows 版](https://www.python.org/downloads/windows/)，建议 3.12，并启用 Python Launcher，然后重试。公司策略禁用安装时联系管理员。 |
| 找不到 ssh.exe | 在 Windows“设置 → 可选功能”中检查 OpenSSH 客户端；安装系统可选功能可能需要管理员。部署脚本不会自动修改系统功能。 |
| pip 下载失败、证书或代理错误 | 根据窗口错误检查网络、公司 CA 和 pip 代理配置后重试；不要关闭 TLS 验证。企业镜像可先在本机设置 `PIP_INDEX_URL`。 |
| 安装停在中间 | 保留报错，修复后重复运行 `install.cmd`；失败不会留下成功标记。 |
| 8765 被其他程序占用 | 先确认占用者，关闭对应应用后重试。脚本不会自动杀进程。 |
| 浏览器没有自动打开 | 手动访问 <http://127.0.0.1:8765/>，检查启动窗口是否已出现服务日志。 |
| 终端能连接、软件不能 | 先确认 Windows 原生 `ssh 别名` 可连接；WSL、其他终端软件的独立密钥库不一定与 Windows OpenSSH 相同。 |
| 进程路径显示权限不足 | 这是远端读取权限问题，和能否 SSH 登录不同；普通采集仍可使用。 |
| 缺少前端构建 | 使用完整分享包；开发者可安装 Node.js 24，运行 `install.cmd -RebuildFrontend -NoLaunch`。 |

## 备份与卸载

停止服务后，按需自行备份 `data`。其中数据库保存机器和规则，`data/keys` 可能保存专用私钥，备份应妥善保管。

删除项目文件夹即可移除项目环境，不会卸载系统 Python 或修改原有 `.ssh/config`。如果启用过自动免密，删除项目不会撤销服务器上的公钥，需要本人核对后撤销相应 `authorized_keys` 条目。若使用过“记住 sudo 密码”，先在软件中删除相应已保存密码；Windows 凭据不在项目文件夹中。
