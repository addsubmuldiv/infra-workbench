# 桌面入口（Windows / macOS）

桌面端使用 Tauri，在独立窗口中加载同一套 React 页面。原来的浏览器入口继续保留；HTTP 和终端 WebSocket 仍连接 `http://127.0.0.1:8765/`，没有放宽同源检查。

本次已完成的检查和待验收项见 [桌面版验证记录](DESKTOP-VALIDATION.md)。

## 使用方式

安装版：Windows 运行 NSIS 安装包，macOS 打开对应芯片架构的 DMG，将应用拖入 Applications。安装包随附 Python 后台，使用者不需要安装 Node.js、Rust 或 Python。

升级安装前，先在托盘或菜单栏退出后台。不要只复制主程序：打包后的 Python 后台必须随应用一起保留。

源码构建完成后，也可以双击项目根目录的 `桌面版.cmd` / `桌面版.command`。原有 `运行.cmd` / `运行.command` 仍作为浏览器入口。

桌面端先检查现有后台；如果后台已运行，就直接复用。没有后台时才启动托盘或菜单栏进程。Windows 托盘在自己的进程中运行后台服务，退出托盘时一并停止后台；再次启动会加载当前代码。如果 8765 端口已被独立后台占用，启动托盘会提示先退出该后台，不会挂接到一个无法随托盘退出的服务。重复启动托盘只保留已有的托盘实例。关闭桌面窗口后监控继续运行；彻底退出后台请使用系统托盘或 macOS 菜单栏。退出桌面窗口会断开该窗口中的普通 SSH 会话；tmux 持久会话可按原来的方式恢复。编辑器存在未保存内容时应弹出关闭确认。

浏览器和桌面端共享后台机器、预约和文件操作数据。两者的主题、机器选择和窗口布局偏好保存在各自的浏览器/WebView 存储中，不自动相互同步。

## 跨平台边界

| 内容 | Windows | macOS |
|---|---|---|
| 页面渲染 | 系统 WebView2 | 系统 WKWebView |
| 后台入口 | Python 系统托盘 | Python/rumps 菜单栏 |
| 安装包 | 当前用户 NSIS 安装包 | .app / DMG，分别构建 Apple Silicon 和 Intel |
| 默认安装版数据 | `%LOCALAPPDATA%\InfraWorkbench` | `~/Library/Application Support/InfraWorkbench` |
| 开发模式数据 | 项目 `data` | 项目 `data` |
| 凭据存储 | 沿用 Windows 凭据管理器 | 沿用 macOS 钥匙串 |

可用 `IWB_DATA` 显式选择既有数据目录。数据、SSH 私钥及凭据不进入安装包。已有源码版与安装版采用不同的默认目录：首次切换时先退出已有后台，再选择所需目录；不会自动复制私人数据。后台已运行时，两个前端都使用该后台当前的数据目录。

两端使用不同的 WebView，需要分别验证字体、文件夹选择、下载、中文输入、剪贴板以及快捷键。窗口宽度变化沿用现有 CSS、resize 和 ResizeObserver 逻辑，不需要手动刷新。

macOS 必须在 Mac 上构建；本机 Windows 测试不能证明 Mac 实机通过。公开分发 Mac 安装包之前，需要用所有者提供的 Apple Developer 身份完成签名和公证。此仓库不包含签名证书或密钥。

## 开发与构建

先按原来的入口准备项目 `.venv` 和 Python 依赖。开发机另外需要 Node.js 24、Rust stable；Windows 需要 MSVC C++ Build Tools、Windows SDK 和 WebView2，Mac 需要 Xcode Command Line Tools。具体前置条件见 [Tauri 官方文档](https://v2.tauri.app/start/prerequisites/)。

安装前端依赖：

```sh
cd frontend
npm ci
cd ../desktop
npm ci
```

开发运行（两个系统相同）：

```sh
cd desktop
npm run dev
```

Windows 构建：

```powershell
.\.venv\Scripts\python.exe -m pip install -r desktop/requirements-build.txt
cd desktop
npm run build
```

macOS 构建：

```sh
.venv/bin/python -m pip install -r desktop/requirements-build.txt
cd desktop
npm run build
```

构建脚本先构建共享前端，再用 PyInstaller 打包 Python 后台，运行独立后台自检，最后构建桌面应用。自检使用临时数据目录和随机本机端口，验证真实 API、前端 HTML 和资源文件，不读取已有机器数据。

输出位置：`desktop/src-tauri/target/release/bundle/nsis`（Windows），`bundle/macos` 与 `bundle/dmg`（Mac）。开发和打包依赖已分别锁定在 npm/Cargo lockfile 中。

`.github/workflows/desktop.yml` 配置 Windows、macOS Apple Silicon、macOS Intel 三种构建。工作流配置不等于已完成远端构建或 Mac 实机验收；需要查看实际运行结果。

## 性能验证

优化后网页版与桌面版的启动、进程树内存和多终端持续输出对照见 [实测报告](DESKTOP-PERFORMANCE.md)。

后续共享前端优化、优化前后实测和跨平台检查见 [第二轮优化记录](PERFORMANCE-FOLLOWUP.md)。

`scripts/measure-ui.cjs` 是 Playwright CLI 测量脚本，拦截该测试浏览器的全部 API 请求，注入 48 台模拟机器、每台 8 个设备。测试不会修改后台配置。运行时请使用独立测试浏览器会话：

```sh
npx --yes --package @playwright/cli playwright-cli -s=desktop-perf open http://127.0.0.1:8765/
npx --yes --package @playwright/cli playwright-cli -s=desktop-perf --raw run-code --filename scripts/measure-ui.cjs
```

脚本测量静置刷新和往返拖动侧栏。应使用相同视口（1440×900）、数据和操作比较，不把浏览器模拟测试当成 WebView2 或 WKWebView 实测。

本次优化使用 `content-visibility:auto` 暂缓屏幕外机器卡片的布局/绘制，并缓存已显示卡片的高度。所有机器数据仍然正常更新；不支持该 CSS 特性的 WebView 会沿用普通布局。

后续验收还需覆盖：多终端连续输出、文件上传下载、编辑保存、窗口最大化/缩放、滚动到列表末尾、主题切换、中文输入、关闭后后台继续运行以及多次启动不重复创建窗口或后台。


Windows 托盘收到资源管理器重启通知时会恢复图标，并每 5 秒检查一次图标是否仍存在；重新注册失败会记录日志并继续重试。此检查只恢复图标，不会另起后台进程。启动、就绪和退出事件记录到本机轮转日志，便于核对托盘与后台生命周期。
