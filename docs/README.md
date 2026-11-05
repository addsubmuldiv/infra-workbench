# 文档目录

第一次使用请从 [README](../README.md) 的下载安装开始，再按 [连接第一台服务器](GUIDE.md#连接第一台服务器) 完成一次操作。本目录按任务分类；英文用户可先看 [English user guide](GUIDE.en.md)。

## 安装与入门

- [Windows 安装、更新、修复与卸载](WINDOWS.md)：区分安装包和源码运行。
- [macOS 安装与验证范围](MACOS.md)：使用前先确认平台限制。
- [使用指南](GUIDE.md)：连接、资源、终端、AI 和通知。
- [浏览器演示](DEMO.md)：不需要服务器或模型密钥的模拟操作。
- [故障排查](TROUBLESHOOTING.md)：按现象检查，找到后续详细说明。

## 日常任务

| 任务 | 文档 |
| --- | --- |
| 添加多台服务器、按集群组织 | [Excel 导入](IMPORT.md) · [集群](CLUSTERS.md) |
| 找空闲设备、查看占卡用户 | [资源与进程](GUIDE.md#查看资源与占卡进程) |
| 等设备空闲后提醒 | [资源预约](RESERVATIONS.md) · [邮件通知](MAIL.md) |
| 回看资源使用情况 | [资源历史](RESOURCE-HISTORY.md) |
| 运行命令、保留长任务 | [终端与 tmux](TERMINAL.md) |
| 编辑、上传和下载文件 | [服务器文件](FILES.md) |
| 打开 TensorBoard 或 Jupyter | [远程服务](PORT-FORWARDING.md) |
| 配置端口转发、打开 VS Code | [SSH 隧道](SSH-TUNNELS.md) |
| 对比训练日志中的指标 | [训练精度对比](PRECISION.md) |
| 使用桌面浮窗、理解关闭与退出 | [浮窗](FLOATING-MONITOR.md) · [后台与通知](BACKGROUND.md) |

资源监控用于观察变化，预约用于等待条件持续满足后提醒，历史用于回看采样。它们都不锁定设备或自动启动训练。

## AI 与外部接入

先看 [AI 使用方式选择](GUIDE.md#选择-ai-使用方式)，再按需要阅读：

- [模型接口配置](AGENT.md)：填写服务地址、密钥及模型，测试连接。
- [本机 Codex](CODEX.md)、[Claude Code 与 OpenCode](EXTERNAL-AGENTS.md)：使用已安装并登录的 CLI。
- [用户技能](USER-SKILLS.md)：保存和复用固定流程。
- [MCP 接入](MCP.md)：让外部 AI 客户端使用工作台能力。
- [数据与凭据](../SECURITY.md)：了解本机存储及发送给模型的信息。

## 开发与维护

[贡献指南](../CONTRIBUTING.md) → [开发者导览](DEVELOPERS.md) → [按功能测试](TESTING.md)。

涉及业务工具先读 [统一 MCP](UNIFIED-MCP.md)，涉及多窗口偏好读 [共享工作空间状态](WORKSPACE-STATE.md)。桌面打包和更新见 [桌面构建](DESKTOP.md) 与 [更新机制](UPDATES.md)。

文件名含 `VALIDATION` 的文档和 `superpowers/` 中的设计、计划用于保留验证或开发记录，不能代替当前版本的使用说明或实机验收。
