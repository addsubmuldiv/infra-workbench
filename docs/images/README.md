# 文档操作图

这些图片来自当前前端界面，使用独立演示环境中的虚构机器、测试网段、示例邮箱和日志，不包含真实服务器地址、账号、密码或训练数据。导入和终端的连接结果为模拟数据，不能作为真实服务器连通性或邮件收件测试的证据。

按文档步骤阅读配图。图中机器名、数值和窗口位置仅作示例；邮箱截图中的 SMTP 地址和邮箱不可直接使用。更新图片时，使用当前构建和示例数据，并同步核对正文中的按钮名称与步骤。

## 桌面浮窗配图

`floating-overview.jpg`、`floating-detail.jpg`、`floating-compact.jpg` 和 `floating-menu.jpg` 使用 `scripts/preview-floating-monitor.py --dpi` 的虚构机器，通过当前 Tkinter 浮窗组件截图。总览、单机详情和收起视图顶部的系统标题栏仅属于临时截图宿主，产品浮窗为无边框窗口。示例未提供显存字段，详情显示「显存未知」；菜单图只展示入口，不代表真实 SSH 连接测试。

`interface-language-en.png` 展示英文设置界面，使用独立浏览器会话和拦截 API 的空白演示数据，未读取或修改真实机器配置。

## 英文文档配图

英文 README、使用指南和浮窗说明使用带 `-en` 后缀的独立截图，中文文档保留原图。`overview-en.png`、`process-details-en.png`、`sudo-settings-en.png` 和 `notification-center-en.png` 来自英文界面的独立浏览器演示环境，所有 API 请求均拦截并返回虚构机器、进程和英文通知，未访问真实服务器。

`floating-*-en.jpg` 来自当前原生浮窗组件的英文预览，使用 Training / Inference / Experiments / Standby 等虚构机器名和示例显存、进程数据。顶部 Monitor preview (sample data) 为临时截图宿主的系统标题栏，产品窗口仍为无边框。
