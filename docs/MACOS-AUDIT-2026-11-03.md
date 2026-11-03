# macOS 检查记录（2026-11-03）

检查版本：`7dab325d3a08bf4ae87ac5265191b2ebd5e6026b`。本次为审查，没有修改产品代码。原有未提交的 12 个文档及截图文件已提交并推送到 origin/main。

## 结论

共享前后端通过了下述本机验证，但不能认定 macOS 各方面正常。原生窗口生命周期和新增设置存在遗漏；现有兼容性 CI 没有实际执行测试。严重性最高的是设置接口绕过 Windows 浮窗的平台限制。

## 发现的问题

### P1：保存启动设置会在 Mac 上启动 Windows 浮窗线程

[Confirmed] `backend/launcher.py:84-88` 无平台判断地调用 `get_monitor_controller()`；`backend/floating_monitor.py:116-166` 默认 enabled=True，构造时就启动线程，在线程内调用 `tk.Tk()`。`launch_monitor()` 的 Windows 限制并不覆盖这条设置接口路径。

即使首次保存的是 show_floating=False，构造控制器也已经请求创建 GUI 线程。本次用替换 ensure_worker 的探针确认了这一点，没有实际启动 Tk。

[Inferred] 在有 Aqua Tk 的 Mac 上，这可能导致原生 GUI 异常甚至进程终止；没有 Tk 的环境则会记录导入失败。不能依赖 Python 的 except 捕获所有原生 GUI 失败。macOS Tk 的主线程要求可见 Python 官方问题记录：https://bugs.python.org/issue7190 。实际 Mac 崩溃尚未复现。

建议：让设置接口返回明确的平台能力；非 Windows 不创建 MonitorController，网页禁用或隐藏 Windows 浮窗选项。

### P1：隐藏窗口后没有处理 Dock 重开

[Confirmed] `desktop/src-tauri/src/main.rs:203-223` 拦截关闭并隐藏窗口，但 run 回调只处理 ExitRequested，没有处理 macOS 的 RunEvent::Reopen。单实例插件的回调只覆盖真正启动第二个进程的情形，插件源码没有替应用处理 Reopen。

[Inferred] 点击 Dock 或通过 LaunchServices 重开已运行应用时，隐藏主窗口不能按预期恢复。Mac 菜单栏的“打开工作台”又固定调用 webbrowser.open，无法作为恢复原桌面窗口的替代入口。尚待 Mac 实机确认。

建议：处理 Reopen，复用 DesktopSession.request_show 和 restore_window。

### P1：兼容性 CI 在创建测试任务前失败

[Confirmed] `.github/workflows/compatibility.yml:22` 在 job 级 env 使用 runner.temp。GitHub 官方上下文表不允许该位置使用 runner，step 级 env 才支持：https://docs.github.com/en/actions/reference/workflows-and-actions/contexts#context-availability 。

实际运行 https://github.com/addsubmuldiv/infra-workbench/actions/runs/41574405472 为 failure，jobs 为空，gh run view 提示 workflow file issue。最近列出的前 8 次兼容性运行也均为 failure。Desktop packages 工作流的运行列表为空。

建议：将测试数据目录变量移至测试 step 的 env，或通过步骤设置 GITHUB_ENV；修正后再执行 Mac CI。

### P2：桌面程序发现与启动偏好未适配 Mac

[Confirmed] `backend/launcher.py:39-44` 只查找三个 .exe 路径。探针创建了实际预期的 macOS .app/Contents/MacOS/infra-workbench-desktop 文件，find_desktop 仍返回 None。因此启动设置会将 Mac 桌面窗口显示为不可用，quick_window 通过此查找器也无法找到 Mac 程序。

`backend/desktop_macos.py:311-315` 及 `scripts/macos_install.py` 仍直接打开浏览器，不读取用户的 LaunchSettings.mode。现有菜单测试也只验证浏览器行为。

建议：为源码构建和安装包分别确定可靠的 Mac 应用定位方式，再将菜单栏打开操作接入统一启动策略。

### P2：菜单栏退出未结束常驻桌面进程

[Confirmed] `backend/desktop_macos.py:370-409` 只关闭菜单、通知队列并停止所属服务，没有 Windows 托盘已有的 shutdown_desktop 调用。Tauri 主窗口本身又采用隐藏常驻策略。

[Inferred] 从 Mac 菜单栏退出后，桌面进程及旧 WebView 可能继续保留，重新启动时复用旧窗口，不符合文档中“彻底退出托盘才结束常驻桌面进程”的描述。不能简单照搬 shutdown_desktop，因为其程序定位也尚未支持 Mac。

### P2：Mac 菜单没有跟进中英文切换

[Confirmed] `backend/desktop_macos.py:300-308` 的菜单文字和测试通知仍是固定中文，没有使用共享 tr，也没有随语言变化重建菜单。Rust 原生下载对话框和工具窗口标题也存在固定中文。

### P2：菜单栏挂接已有服务的行为与文档不一致

[Confirmed] `backend/desktop_macos.py` 复用 `backend.desktop.ServiceHost`。其 ensure() 现在在检测到已有合法后台时直接抛出 RuntimeError，不再挂接；`docs/MACOS.md` 仍描述接入已有服务。Mac 菜单里的 service.owned 分支及测试替身不能证明真实挂接可用。

建议：明确 Mac 是否允许挂接，统一实现、菜单、安装器错误说明和文档。

## 已执行的验证

- [Confirmed] Windows 后端全量：657 passed、11 skipped、13 warnings，耗时 148.85 秒。警告为依赖内部 asyncio.iscoroutinefunction 弃用提示。
- [Confirmed] 前端：231 项通过；TypeScript 检查与 Vite 生产构建通过。构建有大 chunk 提示。
- [Confirmed] Rust 桌面层：8 项通过，编译目标为本机 Windows，不覆盖 cfg(macos) 代码。
- [Confirmed] WSL Ubuntu 真实 POSIX PTY：控制终端、初始尺寸、中文与 emoji 输出、输入、resize 调用、所属子进程清理通过；不代表 macOS 原生 PTY 已测试。
- [Confirmed] Windows WebKit 27.2：正常模式及移除 randomUUID/Array.at/WebGL2 的模式均通过。480/800/1440 宽度无横向溢出；两轮终端各完整确认 129344 字节；文件编辑保存、20 字节上传、终端输入和未保存编辑器保留通过；pageerror 均为空。使用模拟服务器，没有连接真实 SSH。

WebKit 原有脚本不能直接通过：演示数据没有 profiles，文件流程没有 workspace-state 路由，设置页也改为分栏。这次仅在被 git 忽略的 work 目录创建临时副本，补齐当前接口数据并调整设置页等待条件；没有将临时适配冒充为原脚本通过。结果保存于 `work/performance-round2/webkit-compat.json`，截图同目录。

复查命令（项目根目录）：

```powershell
.venv/Scripts/python.exe -m pytest tests -q
npm --prefix frontend test
npm --prefix frontend run build
& "$env:USERPROFILE/.cargo/bin/cargo.exe" test --locked --manifest-path desktop/src-tauri/Cargo.toml
node work/macos-audit-webkit.cjs
gh run view 41574405472 --json jobs,conclusion,event
git status --short
```

## 未验证范围

[Unknown] Intel / Apple Silicon 的真实打包安装与启动、签名公证、Finder 权限提示、钥匙串授权与重启后读取、rumps/PyObjC 事件循环、真实通知及点击、登录启动、Dock 恢复、多屏和 Retina、中文输入法、WKWebView 剪贴板及原生保存对话框。

没有 Mac，也没有触发新的收费或外部 CI 构建。本机测试、Linux PTY 和 Windows WebKit 不能证明这些原生行为。
