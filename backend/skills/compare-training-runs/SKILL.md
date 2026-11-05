---
name: compare-training-runs
description: 比较两份训练日志的 loss、grad_norm 等指标，按真实 step 对齐计算误差，查看差异原始行，保存或恢复对比配置。
---

# 精确对比训练日志

1. 确认两份日志的真实机器和路径。可用 list_log_comparisons 读取已有配置；路径缺失先询问，或按用户指定目录 browse_training_logs/search_server_files。
2. 对两份日志分别 read_training_log，保留返回快照 ID，核对轨迹、指标、解析警告与截断情况。快照过期后重新读取，不能编造 ID。
3. 多个 rank/训练段时询问需要的 group；重复 step 不自行选 first/last，先解释并确认策略。
4. compare_training_logs(baseline=快照ID, candidate=快照ID, metrics=[...]) 由确定性程序完成共同 step 对齐和数值计算。不要让模型凭抽样行自行估算全量误差。
5. 默认返回全量对齐统计和首条、最大误差、末条证据，不返回完整曲线。根据统计说明共同范围、缺失 step、误差及适用条件；不要把证据样本说成全部数据。需要逐步数值时传 view="page"、offset 和 limit，按实际 next_offset 继续；每页保留全量统计。需要查证差异时调用 get_log_record，引用真实原始行。Summary statistics cover all aligned steps; point evidence is sampled. Use view="page" for exact paginated details.
6. 用户要求保存时才 save_log_comparison；删除配置才 delete_log_comparison。配置保存的是机器/路径和对比条件，不是日志副本。
7. 下载用 download_training_log，handoff_required 只是给客户端的请求参数，不声称文件已下载。
