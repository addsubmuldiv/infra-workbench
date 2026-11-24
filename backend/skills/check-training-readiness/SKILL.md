---
name: check-training-readiness
description: 启动训练前检查选定机器的 GPU/NPU、显存、进程和通信端口，解释 PASS/BLOCK/UNKNOWN。
---

# 训练前检查

1. 未确定机器或设备编号时，按需要用 list_hosts、search_hosts 或 get_resources 读取后台最新采样，确认真实设备 ID。已有明确的机器和设备编号时直接使用。按同机同类型计算卡数，多芯片不等于物理卡。
2. 确认用户要求的设备、每卡最低显存 minimum_gib 和通信端口 port（默认 29500）。
3. 调用 preflight(host_id, devices, minimum_gib, port)。它会发起或复用同机正在进行的采集，由软件根据结果判断。调用前无需另外刷新。
4. 分别解释 PASS、BLOCK、UNKNOWN 及工具返回原因。采集失败、进程信息缺失不能解释为空闲。
5. PASS 只表示本次条件检查通过，不保证后续仍空闲或端口能绑定，也没有锁定资源或启动任务。用户要等资源时再用预约技能。
