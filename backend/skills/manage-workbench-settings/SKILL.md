---
name: manage-workbench-settings
description: 用户想查看或修改工作台设置时使用，例如换主题、切换中英文、打开页面、调整筛选、字号、侧栏、默认预约时长、采集频率、启动方式或助手模型。
metadata:
  include_tools: get_workbench_preferences set_workbench_theme set_workbench_language update_workbench_preferences get_launch_settings update_launch_settings open_floating_monitor get_workbench_health set_refresh_interval set_host_alias set_host_collection get_workbench_state get_workbench_model_settings activate_workbench_model_profile set_workbench_model test_workbench_model mark_notifications_read get_terminal_workspace update_terminal_settings clear_terminal_history
---

# 管理工作台设置

- 换主题用 `set_workbench_theme`。玻璃暗色对应 `glass-dark`，午夜对应 `midnight`，石墨对应 `graphite`。用 `get_workbench_preferences` 核对当前主题和可选 ID。只说“换个暗色主题”时可用 `midnight`，并告知选了午夜。
- 界面语言用 `set_workbench_language`，简体中文为 `zh`，英文为 `en`。只要求用某种语言回复时直接用该语言回复。
- 页面、侧栏、找卡筛选、终端显示、浏览器通知和默认预约时长用 `update_workbench_preferences`，只提交要求变更的字段。网页会同步后台设置，发送实际浏览器通知仍需要浏览器权限。
- 通知中心全部已读用 `mark_notifications_read`。指定机器的终端命令历史开关、完成提醒和 sudo 复用偏好用 `update_terminal_settings`。用户明确要求清除工作台终端命令历史时用 `clear_terminal_history`。
- 修改主机别名或暂停采集时，先核对机器 ID。修改全局采集间隔用 `set_refresh_interval`。采集设置可用 `get_workbench_state` 读回。
- 修改启动方式或桌面浮窗开关时，先调用 `get_launch_settings`，将用户未要求修改的字段原样带入 `update_launch_settings`。用户要求立即显示浮窗时用 `open_floating_monitor`。
- 切换已保存的模型配置前用 `get_workbench_model_settings` 核对配置；切换或修改模型应用于后续请求。连接测试会请求该模型服务，仅在用户明确要求测试时做。
- 写入成功后报告实际保存的值。需要批准时等批准结果，有错误或结果不明时先读回。
