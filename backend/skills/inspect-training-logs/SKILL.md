---
name: inspect-training-logs
description: 读取训练日志，解释 loss、grad_norm、报错和任务进展，或对照两份日志。用户问训练是否正常、哪里失败、两次训练是否一致时使用。
---

# 检查训练日志

1. 用 list_hosts 确定机器，再用 read_server_directory 找到用户指定的日志。路径不明时先确认，不猜文件名。
2. read_server_file 按行读取，检查实际 step、时间、指标和报错。按需分页，不以截断片段代表完整日志。
3. 对比日志时按相同 step、指标单位、训练配置与统计口径比较；缺失 step 或重复记录需说明。
4. 需要核对任务是否仍在运行时，使用 search_fleet(scope="processes") 或 ssh_check(check="processes")。
5. 区分日志明确记录的事实和可能原因。不要仅凭 loss 波动断言收敛，不要仅凭进程消失断言训练成功。

大量日志逐 step 数值对比读取 compare-training-runs 技能，调用 read_training_log 和 compare_training_logs，由软件计算；按行抽样不能代替完整对齐统计。
