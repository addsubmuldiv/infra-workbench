---
name: inspect-training-logs
description: 读取训练日志，解释 loss、grad_norm、报错和任务进展，或对照两份日志。用户问训练是否正常、哪里失败、两次训练是否一致时使用。
metadata:
  include_tools: find_hosts list_hosts read_server_directory read_server_file tail_server_file search_file_contents read_training_log
---

# 检查训练日志

1. 复用已核实的 host_id；别名用 find_hosts，型号/IP 先读 find-hosts 技能。用户给出完整日志路径时直接读取，只有路径缺失才浏览目录；机器完全未知时才 list_hosts。不猜文件名。
2. 问最新进度、最后报错或最近 loss 时先 tail_server_file；需要精确指标统计时 read_training_log 取得解析概况和快照 ID，原始证据按需 read_server_file 或 search_file_contents。尾部片段不能代表完整训练，也不证明进程仍存活；只有确需早期上下文才补读开头，不整份逐页读取。
3. 对比日志时按相同 step、指标单位、训练配置与统计口径比较；缺失 step 或重复记录需说明。
4. 只有用户要求核对任务是否仍在运行时，再读 inspect-processes 技能补查对应机器的进程；不为解释日志自动扩展成全机巡检。
5. 区分日志明确记录的事实和可能原因。不要仅凭 loss 波动断言收敛，不要仅凭进程消失断言训练成功。

大量日志逐 step 数值对比读取 compare-training-runs 技能，调用 read_training_log 和 compare_training_logs，由软件计算；按行抽样不能代替完整对齐统计。
