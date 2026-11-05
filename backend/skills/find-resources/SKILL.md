---
name: find-resources
description: 查找满足卡数、显存、设备类型要求的空闲 GPU/NPU 机器，或继续调整上一轮筛选条件。用户找卡、找空闲机器、问哪里能跑训练时使用。
---

# 寻找设备资源

用户用自定义机器别名（如“训练机 A3”）指代目标时，先用 `find_hosts(name="训练机 A3")` 查找。`name` 同时匹配自定义别名和原 SSH 连接目标；同名时继续核对，后续操作使用真实 `host_id`。


用户只是用型号、IP 或卡数指代某台机器（包括待查看/停止进程的机器）时，先读取 find-hosts 技能，用 find_hosts 定位；不能用空闲资源筛选排除正在使用的目标机器。

1. 概况直接用 search_fleet，scope="resources"、view="summary"，传用户要求的 kind、count、min_free_gib、idle 等筛选字段。结果含真实 host_id，不需要先 list_hosts 或按别名分批枚举机器。界面限制的机器范围不可扩大。
2. 要求当前状态时首轮传 refresh=true。先看 total、next_offset 和 coverage；有下一页时保持条件一致，用 offset=next_offset、refresh=false 继续。不把第一页或被截断的结果说成全部结果。summary 按型号提供设备 ID、设备数、可确认的物理卡数和每设备空闲显存最小/最大值；显存范围不同就报告范围，不取平均冒充每卡数值。
3. 同一台机器、同一种设备的卡数必须同时满足；不能跨机器凑卡。多芯片 NPU 的设备数不能直接当作物理卡数。
4. 内置会话继承上一轮条件时只传用户修改的字段；切换 scope 会重置旧条件。外部 MCP 客户端应从对话补齐完整筛选参数，不依赖服务端跨请求存储。具体参数以工具 schema 为准。
5. 检查采样时间、状态和 coverage；未知、采集失败和过期均不能视为空闲。刚刷新成功且完整的结果可直接回答，不再逐机 get_resources 或 search_hosts 重复刷新。只有用户要逐卡详情、结果不足或准备执行操作时，才针对必要机器补查；详情可用 view="detail" 或 get_resources。没有物理卡数证据时只报告设备数。
6. 告诉用户实际候选、条件和未查清部分。无匹配时解释缺少的设备或显存，不擅自降低要求。

查询不会锁定或预留设备。用户明确要求约机器时读取 manage-reservations 技能，通过 MCP 创建预约；没有成功结果不能声称已预约。训练前检查读取 check-training-readiness。

Efficiency: query the fleet directly with view="summary", reuse fresh complete results, paginate with refresh=false, and fetch per-device details only when needed. Never treat missing or stale data as idle.
