---
name: find-resources
description: 查找满足卡数、显存、设备类型要求的空闲 GPU/NPU 机器，或继续调整上一轮筛选条件。用户找卡、找空闲机器、问哪里能跑训练时使用。
---

# 寻找设备资源

用户按名称指定目标时，先把原名称传给 `resolve_target`。机柜、集群或工作台分组传 `type="cluster"`，找到唯一分组后把 `cluster_id` 传给每项资源查询。单机详情用返回的 `host_id`。有歧义时请用户确认，查不到时核对原名称。


用户只是用型号、IP 或卡数指代某台机器（包括待查看/停止进程的机器）时，先读取 find-hosts 技能，用 find_hosts 定位；不能用空闲资源筛选排除正在使用的目标机器。

1. 概况直接用 search_fleet，scope="resources"、view="summary"，传用户要求的 kind、count、min_free_gib、idle 等筛选字段。结果含真实 host_id，不需要先 list_hosts 或按别名分批枚举机器。界面限制的机器范围不可扩大。
2. 要求当前状态时首轮传 refresh=true。先看 total、next_offset 和 coverage；有下一页时保持条件一致，用 offset=next_offset、refresh=false 继续。不把第一页或被截断的结果说成全部结果。summary 按型号提供设备 ID、设备数、可确认的物理卡数和每设备空闲显存最小/最大值；显存范围不同就报告范围，不取平均冒充每卡数值。
3. 同一台机器、同一种设备的卡数必须同时满足；不能跨机器凑卡。多芯片 NPU 的设备数不能直接当作物理卡数。
4. 内置会话按 scope 继承已明确的筛选条件，包括 `search_fleet` 的 `cluster_id`。用户明确切回全局时传 `cluster_id=null`。外部 MCP 客户端应在每次调用中补齐完整筛选参数。
5. 检查采样时间、状态和 coverage；未知、采集失败和过期均不能视为空闲。刚刷新成功且完整的结果可直接回答，不再逐机 get_resources 或 search_hosts 重复刷新。只有用户要逐卡详情、结果不足或准备执行操作时，才针对必要机器补查；详情可用 view="detail" 或 get_resources。没有物理卡数证据时只报告设备数。
6. 告诉用户实际候选、条件和未查清部分。无匹配时解释缺少的设备或显存，不擅自降低要求。

查询不会锁定或预留设备。用户明确要求约机器时读取 manage-reservations 技能，通过 MCP 创建预约；没有成功结果不能声称已预约。训练前检查读取 check-training-readiness。

同时查看空闲资源、占卡进程和 TCP 监听概况时，用 get_fleet_overview 一次读取允许范围内的最近有效采样。只有用户明确要求立即重采时才传 refresh=true。检查 coverage 和 next_offset，并说明采样缺失、过期或端口进程名不可见。TCP 监听摘要只提供少量示例，核对指定服务再做必要的专项检查。要分别筛选资源和进程时，用 search_fleet；并行查询可共享同机刷新，翻页 refresh=false。进程 summary 按机器、用户和详情状态分组，commands 列出名称及命令前缀，processes 的每个 PID 与设备列表通过 command_index 对应 commands 条目，组内保留用户和采样时间；total/offset 按组计，process_count 是组内进程数。命令仅为带截断标记的前缀，相同前缀不证明完整命令相同；需确认完整启动参数、模型路径或工作目录时，再对相关机器用 view="detail" 或 inspect_server_process 补查，不从前缀推断缺失参数。

Efficiency: query the fleet directly with view="summary", reuse fresh complete results, paginate with refresh=false, and fetch per-device details only when needed. Never treat missing or stale data as idle.
