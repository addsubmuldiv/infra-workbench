# macOS 使用说明

Mac 作为工作台客户端，通过 SSH 管理 Linux 上的 GPU / Ascend NPU 服务器，桌面安装包优先支持 Apple Silicon。源码运行的目标环境为 macOS 11+、Python 3.11+；桌面包的构建配置最低为 macOS 12。**菜单栏、钥匙串授权、真实通知和干净系统安装尚待 Mac 实机验收。**

## 桌面安装包（实验性）

从 [v0.1.2 Release](https://github.com/addsubmuldiv/infra-workbench/releases/tag/v0.1.2) 下载 Apple Silicon 的 `.dmg`：

- Apple Silicon：`Infra-Workbench-0.1.2-darwin-aarch64.dmg`。
Intel Mac 暂不提供桌面安装包。

打开磁盘映像，将应用拖到 Applications 后启动。桌面包包含 Python 后台与前端资源，无需另装 Python 或 Node.js；外部 Codex、Claude Code、OpenCode 仍需自行安装和登录。手动升级前保存编辑内容并退出旧菜单栏后台。

这些包由 GitHub 的 macOS runner 构建和测试，尚未做 Apple Developer ID 签名或公证。更新产物的密码学签名不等于 Apple 代码签名；首次打开可能受到 Gatekeeper 限制，请核对来源后按系统提示处理，不要关闭系统安全保护。构建成功不能替代原生交互及真实设备验收。macOS 当前仍以手动安装和更新为主。

## 源码安装和启动

1. 准备 Python 3.11+，可使用已有 Homebrew Python，或 [Python 官方安装包](https://www.python.org/downloads/macos/)。
2. 完整克隆仓库或解压代码，双击根目录的 **`运行.command`**。
3. 首次创建项目内的 `.venv` 并安装依赖；菜单栏和本地服务就绪后自动打开网页。以后仍双击同一文件。

不需要 Node.js，不会自动安装 Homebrew、修改系统 Python 或要求本机 sudo 密码。启动器会查找常见 Homebrew 和 Python 官方安装位置。Mac 与 Windows 分别创建环境，不能复制 `.venv` 通用。

Git 克隆保留执行权限。若 ZIP 解压后双击提示没有执行权限，在项目目录的终端执行一次：

```sh
chmod +x 运行.command
```

出错时终端保留错误供查看。若系统阻止打开，请按 macOS 正常流程检查来源后自行处理，不需要关闭系统安全保护。

## 菜单栏与通知

菜单栏提供打开工作台、查看预约、通知开关、测试通知、登录启动和退出。关闭网页或安装终端后，后台继续运行。退出只停止菜单栏自身启动的后台；接入已有服务时，不停止原服务。

设置中的“启动时打开”可选择浏览器或已构建、安装的桌面窗口；菜单栏“打开工作台”和 `运行.command` 都遵循这个选择。桌面窗口关闭后会隐藏，点击 Dock 图标可恢复。退出拥有后台的菜单栏时，也会退出常驻桌面窗口。桌面资源浮窗目前仅支持 Windows，Mac 设置页不提供浮窗开关。菜单栏文字跟随工作台的中英文设置。

- 已安装 `terminal-notifier` 时，通知可携带查看机器和设备的链接。
- 未安装时使用系统自带通知，**此后备方式不支持精确点击跳转**；从菜单栏进入预约页查看即可。软件不自动安装这个可选工具。
- 系统接受请求不代表通知已显示或已读；专注模式、权限和系统策略可能抑制提示。也可开启网页浏览器通知，或为预约勾选邮件。

登录启动默认关闭，只在用户主动开启后写入当前用户的应用专属 LaunchAgent，下次登录生效。移动或删除项目之前，先从菜单栏关闭该选项。

## 密码与终端

SSH 密码、sudo 密码和邮件授权码分别保存在当前用户的 **macOS 钥匙串**，各设置页可删除。没有明文文件回退，也不将密码放进命令行参数。系统可能要求钥匙串授权；无法读取时显示错误，不会当成密码已删除。

本机 OpenSSH 读取 `~/.ssh/config`，继续使用已有密钥、SSH agent 和跳板；首次连接需自行核对主机指纹。[Excel 导入](IMPORT.md) 沿用相同配置。网页终端使用本机 POSIX PTY，已有密码连接仍通过 AsyncSSH 建立独立通道。

支持 **⌘C / ⌘V / ⌘F** 复制、粘贴和查找，**⌘点击** `pwd` 输出路径打开目录，文件编辑支持 **⌘S**。未选择文字时，**Control+C** 仍发给远端中断命令。远端 tmux、Bash 和 Python 要求见 [终端说明](TERMINAL.md)。

## 更新和排障

保存文件并处理好普通终端任务，从菜单栏退出后台；更新代码后重新双击 `运行.command`。刷新网页不能替代后台重启。已有 tmux 任务留在远端，新版增强脚本由更新后新建的持久会话加载。

- 找不到 Python：确认版本至少为 3.11，再重试。
- 安装失败：检查终端中的网络、证书或依赖错误；修复后再次双击，可复用环境。
- 服务在线但没有菜单栏：查看 `data/macos-launch.log`、`data/macos-desktop.log`。启动器会同时检查后台与菜单栏。
- 另一个项目副本正在运行：先退出旧副本的菜单栏，再启动新副本。

开发者可使用这些参数；环境检查通过不代表原生功能已验证：

```sh
./运行.command --check-only
./运行.command --install-only
./运行.command --repair --no-browser
```

## 验证范围

### Apple Silicon 构建与本地服务验证（2026-11-06）

v0.2.2 已在 Apple Silicon、macOS 27.0.1、Python 3.12.15 和 Rust 1.99.1 环境完成无签名开发构建，生成 `.app` 和 `.dmg`。前端生产构建、打包后台独立自检、`pip check` 和 DMG 校验通过。后台自检使用临时数据与本机随机端口，覆盖 API、静态资源、原生 PTY，以及 SSH/SFTP 和助手依赖的本地检查，不代表真实远端服务器或模型服务已验证。

在项目根目录准备环境并构建（`python3.12` 可替换为已安装的 Python 3.11+）：

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt -r desktop/requirements-build.txt
npm --prefix frontend ci
npm --prefix desktop ci
IWB_UNSIGNED_BUILD=1 npm --prefix desktop run build
hdiutil verify "desktop/src-tauri/target/release/bundle/dmg/Infra Workbench_0.2.2_aarch64.dmg"
```

Node.js 和 Rust 的要求见[桌面构建说明](DESKTOP.md#开发与构建)。`IWB_UNSIGNED_BUILD=1` 仅用于开发安装包，不生成签名更新产物，也不完成 Apple Developer ID 签名或公证。版本变化后应使用实际输出的 DMG 文件名。

若默认端口已有工作台运行，可使用隔离数据目录和另一端口验证新副本，避免中断原服务：

```sh
IWB_DATA="$PWD/work/macos-smoke-data" .venv/bin/python -m uvicorn backend.app:app --host 127.0.0.1 --port 8876
```

保持该命令运行，在浏览器打开 `http://127.0.0.1:8876/`，结束后用 Ctrl+C 停止。这是网页服务验证入口，不启动菜单栏或桌面外壳。本次在 Codex 内置浏览器确认首次引导、算力总览、新建空白助手对话和设置页面可加载，健康接口返回 v0.2.2。没有配置真实主机或模型；菜单栏、钥匙串、通知、原生桌面窗口和干净系统安装仍未验收。

已增加凭据、安装器、菜单栏和终端测试，以及 macOS CI 配置。Windows 上运行模拟边界测试，WSL Linux 可执行真实 POSIX PTY 测试。**Linux 结果不能证明 macOS 系统行为；新增 CI 配置也不等于已在远端执行成功。**

拿到 Mac 后仍需确认 Finder 双击启动、钥匙串授权及重启后读取、菜单栏退出与登录启动、真实通知显示和点击，以及 SSH 输入、缩放和清理。先用自己的测试机器和临时凭据验证。
