---
name: analyze-resource-changes
description: 查询资源历史、空闲时长和采样覆盖，或者排查设备释放、进程出现或消失、采集失败和其他变化。
metadata:
  include_tools: find_hosts resolve_target get_cluster get_resource_history read_changes get_resources search_fleet read_server_file
---

# 分析资源变化

1. 确认需要的机器范围和时间段。统计空闲时长、覆盖率或连续空闲时段时，用 get_resource_history，传入机器 ID 和当地日期及 IANA 时区，或给定带时区的起止时刻。默认概要按机器分页；查时段用 view="segments"，指定 segment_host_id 查看单机。沿用响应的时间范围，不把 unknown 算作空闲。查询事件用 read_changes，hours 只接受 1、6、24、168。
2. read_changes 返回受本轮机器范围约束的历史记录。引用真实记录编号、机器和采集时间。
3. 用 get_resources(refresh=true) 或 search_fleet(refresh=true) 区分历史变化与当前状态。
4. 采样间隔中的变化时间只能限定在相邻观测之间，不能捏造精确退出时间。
5. 进程消失只说明后续观测没有看到，可能是完成、失败或被停止；需要 read_server_file 读取日志补证据。采集失败不代表资源释放。

明确记录覆盖范围、截断情况和未知部分。没有原始证据时不给出确定原因。
