---
name: analyze-resource-changes
description: 查询最近的资源变化、设备释放、进程出现或消失以及采集失败记录。用户问什么时候空出来、刚才发生什么、资源变化原因时使用。
---

# 分析资源变化

1. 确认需要的机器范围和时间段。read_changes 的 hours 只接受 1、6、24、168；时间用 Asia/Hong_Kong 说明。
2. read_changes 返回受本轮机器范围约束的历史记录。引用真实记录编号、机器和采集时间。
3. 用 get_resources(refresh=true) 或 search_fleet(refresh=true) 区分历史变化与当前状态。
4. 采样间隔中的变化时间只能限定在相邻观测之间，不能捏造精确退出时间。
5. 进程消失只说明后续观测没有看到，可能是完成、失败或被停止；需要 read_server_file 读取日志补证据。采集失败不代表资源释放。

明确记录覆盖范围、截断情况和未知部分。没有原始证据时不给出确定原因。
