# Changelog

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
