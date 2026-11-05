# Changelog

## 0.2.2 — 2026-11-05

### 更新内容

本次更新包含 v0.2.1 到 v0.2.2 之间的助手、监控、资源历史、界面和分发改动。

#### AI 助手与 MCP

- 优化跨机器资源与占卡进程查询：支持汇总查询、独立只读工具并行调用，复用进行中的采集，减少不必要的模型往返和重复刷新。
- 优化日志分析、实验查找、文件读取、精度对比与预约等常用技能：已知路径直接读取、近期日志优先读取尾部，独立日志可以并行检查。
- 使用框架原生的工具按需披露、大结果卸载和分页读取，限制资源、进程、历史、文件和日志结果进入模型上下文的体积；超限时提供明确提示。
- 增加跨会话长期记忆，按模型配置和机器范围隔离保存偏好与已确认约定，可要求助手记住或忘记；历史采样不作为当前资源状态的依据。
- 修正工具按需披露后的上下文预算、模型容量识别与压缩触发计算，改善上下文用量显示。
- 改进 Responses 工具调用的可选参数处理及原生 MCP 结果传递，减少多余的结果包装和重复内容。

#### 资源监控、历史与日志

- 修正完整 NPU 进程表中未列出进程的空闲芯片识别；不完整或无效数据仍保留未知状态。
- 为 npu-smi 查询增加超时余量，并减少监控采集状态对界面的反复干扰。
- 修复资源历史采样覆盖区间的判断，避免只读查询创建的运行记录错误截断已有历史。
- 修正历史图中未知数量的绘制范围，增加区间悬浮提示，展示精确时间、空闲数量和数据完整性原因。
- 训练日志增加 optimizer_steps 步数识别，支持按该步数进行指标对齐和精度对比。

#### 界面与启动体验

- 明确区分机器列表中的已选数量、在线数量和已添加数量，完善资源总览统计说明。
- 修复集群操作菜单被容器裁切或超出短窗口的问题，并改进筛选状态与空结果提示。
- 刷新默认值由统一策略配置控制，恢复默认后继续跟随该配置；手动设置仍优先。
- 安装版默认打开桌面窗口；快捷方式、托盘和浮窗入口遵循已保存的浏览器或桌面启动方式。
- 打开其他界面时复用健康后台；选择浏览器模式后保留后台监控与已有桌面终端会话。
- 修复 Windows 启动器安装相关问题；设备详情抽屉先准备首帧，再缓慢滑入，遮罩同步渐暗。

#### 开发与分发

- 将版本号集中到 version.json，统一同步前端、桌面端、锁文件及后台版本。
- 集中管理带注释的内部策略参数，生成前后端与远端探针常量，增加源码分发和冻结后台中的一致性检查。
- 新增按功能分组和前后端范围选择的测试入口，补充中英文开发者导览与验证说明。

#### 兼容性变化

- 内置模型接口统一使用 Responses，移除自动回退到 Chat Completions 的路径。旧配置保留地址和密钥并迁移协议；服务商或网关需要支持 Responses 及函数工具调用。
- 移除原自动化工作流功能及对应界面入口。

### 验证与安装

后端全量测试 1078 项通过、15 项跳过；前端 361 项、发布工具 14 项、Rust 27 项通过。签名构建和冻结后台自检通过，上传附件已核对 SHA256。真实原生窗口动画、干净系统安装和实际覆盖升级未在本轮实测，不以构建或模拟测试替代实际体验验证。

提供 Windows x64 安装包、更新签名、latest.json 和 SHA256SUMS.txt。本版本不提供 macOS 包。更新文件经过应用更新公钥的签名校验；安装程序没有 Windows Authenticode 签名。手动覆盖安装前请保存文件，并从托盘退出旧后台。


## 0.2.1 — 2026-11-05

- 修复 Windows 安装版 SSH 认证初始化时报 `No module named 'win32timezone'` 的问题。
- 补齐 bcrypt 依赖，支持读取带口令的 OpenSSH 私钥。
- 扩展冻结后台自测，覆盖本机 SSH 密码/密钥连接、SFTP、Excel、助手执行、图片、证书、时区及远端探针资源。
- 构建时将运行库复制到中文及空格路径，脱离项目目录和开发环境检查，减少安装后才暴露的依赖缺失。
- 补充桌面版所需的 Windows OpenSSH 客户端说明。

本版本仅提供 Windows x64 安装包及正式签名的更新文件。安装程序未做 Authenticode 签名。

## 0.2.0 — 2026-11-05

- 明确机器侧栏的筛选范围与状态展示，改进分组和批量选择体验。
- 新增批量 SSH 隧道管理，支持按机器范围查看和操作隧道，并同步更新使用文档。
- 包含 0.1.8 的 Windows 首次启动与启动页样式修复。

本版本提供本地构建的 Windows x64 安装包、正式更新签名、更新清单和校验和。

## 0.1.8 — 2026-11-05

- 修复 Windows 原生入口未能自动拉起后台的问题：查询系统监听表，避免连接拒绝被短 HTTP 超时掩盖。
- 修复启动页样式受 CSP 拦截导致图标铺满窗口、布局失效的问题，并与工作台共用静态样式。
- 启动失败后停止等待计时，明确显示加载已停止；新增原生启动日志记录后台进程启动和失败原因。
- 增加真实 Tauri WebView 布局与 CSP 验证，以及端口无人监听、HTTP 超时和正常健康响应的回归测试。

本版本仅提供本地构建的 Windows x64 安装包及已签名更新文件。

## 0.1.7 — 2026-11-05

- 优化 Windows 启动速度，提前显示启动界面、阶段进度和等待提示。
- 修复打包混入旧前端资源、旧版本产物和测试依赖的问题，增加哈希、签名及版本校验。
- 覆盖升级清理旧运行库；安装失败或取消时恢复旧程序和配套依赖，并保留用户数据。
- 新增首次使用引导并更新使用文档。
- 优化长对话渲染、实时监控更新及多机采集调度，增加刷新诊断信息。

本版本在本地构建并验证 Windows x64 安装包，提供自动更新签名、更新清单和校验和；不包含 macOS 安装包。

## 0.1.5 — 2026-11-05

- 新增机器别名，并同步到机器列表、助手查询和悬浮监控窗口。
- 新增独立 SSH 隧道管理和 VS Code 启动入口，可在启动前建立所选隧道。
- 新增集群批量终端与命令操作、资源预约和按日资源历史，支持选择历史时间范围。
- 改进助手独立窗口、终端命令填入、API 与模型选择恢复，以及模型列表缓存。
- 改进 SSH 会话与工作区偏好恢复、密钥导入、监控刷新及设置导航。
- 修复托盘、后端和原生窗口的生命周期协调问题。

本版本按默认发布流程提供 Windows x64 安装包和已签名的自动更新文件。安装程序尚无 Authenticode 签名；本次不包含实验性 macOS 安装包。

## 0.1.2 — 2026-11-03

- AI 助手新增本机 Codex、Claude Code 和 OpenCode 执行引擎，与现有模型接口并存，共用受限 MCP 工具、机器范围和执行记录。
- Codex 支持真实 thread 续聊、执行中补充指令和取消；CLI 子进程可继承系统代理，本机 MCP 连接始终绕过代理。
- 终端选区、当前屏幕可作为有界附件发送给助手，支持预览、移除、来源信息和凭据脱敏。
- 机器卡片新增远程服务入口，管理 TensorBoard、Jupyter 和自定义 HTTP 服务的本机回环 SSH 转发。
- 终端支持可配置关键词高亮，以及默认关闭、有像素和内存限制的 SIXEL / iTerm 图片显示。
- Ctrl / Command 点击独立的压缩包路径可填入引用后的解压命令，需在空命令行自行按回车执行。
- 新增可检查的自动化草稿、手动运行、运行记录和取消；可信终端事件可在用户启用后触发，输出触发仅读取。
- 对话可从上一轮之前创建分支，恢复草稿、附件、技能和机器范围；已执行操作不会回滚。
- 加强范围与引擎切换的模型历史隔离，修复取消竞态、原生转发就绪判断和图片迟到解码处理。
- 修复 Windows 发布测试 HTTP fixture 的 socket 模式继承问题。

Codex 和 Claude Code 已通过真实 CLI、合成 MCP 工具、续聊及取消验证；Codex 另通过完整工作台 77 工具目录验证。OpenCode 1.19.5 的配置隔离已验证，但模型试跑超时，尚未完成认证 provider 的端到端验收。CLI 不包含在安装包中，需自行安装并登录。原生 macOS 验收仍待完成。

本次未加入终端分屏、全局传输中心、双窗格文件管理或 AI 训练日志接入。Windows 更新包有更新签名，安装程序尚无 Authenticode 签名；仓库保持私有，匿名自动更新源不可达时请手动下载。

## 0.1.1 — 2026-11-03

- Windows desktop updater with quiet startup checks and manual check/download/install controls.
- Cryptographically signed update packages and version-bound signatures; public GitHub Release latest.json feed.
- Progress, release notes and retry, with native confirmation before installation.
- All-window unsaved-work checks, backend activity/drain protection and recovery on failed installer launch.
- Browser, demo, development and macOS builds do not run the Windows automatic installer.

Existing 0.1.0 users must manually install this bootstrap version once. Save work and exit the old tray/backend before installation. Future releases can use the updater after the repository is public. Signing keys are private; updater signing does not provide Windows Authenticode signing.

## 0.1.0 — 2026-11-03

Initial Windows x64 release of Infra Workbench.

- GPU and Ascend NPU resource overview, process inspection and idle-device alerts over SSH.
- Integrated terminals, file management, training-log comparison, AI assistant, MCP and Skills.
- Isolated browser demo with synthetic hosts and a spotlight onboarding guide.
- Bundled Python backend and NSIS setup wizard; the application footer displays v0.1.0.

The Windows installer is unsigned. Clean Windows install/upgrade/uninstall and native macOS acceptance remain pending. This release includes no macOS installer. Read SECURITY.md before enabling remote command or credential access.
