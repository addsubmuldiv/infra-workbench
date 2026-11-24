---
name: manage-reservations
description: 用户要求约机器、等待空闲卡、修改或取消预约，以及设置或删除设备监控提醒时使用。支持单机指定设备或设备数量、指定多台机器、集群内任意几台。
metadata:
  include_tools: find_hosts get_resources get_workbench_state create_reservation update_reservation cancel_reservation get_mail_settings create_rule delete_rule resolve_target get_cluster list_group_reservations get_group_reservation create_group_reservation update_group_reservation cancel_group_reservation rebook_group_reservation delete_group_reservation
---

# 预约和监控

1. 分清用户是查询资源还是要求预约。只有明确要求写入时才创建/修改/取消；不因为找到了空闲卡就自动预约。
2. 复用已核实的 host_id，或用 find_hosts 按别名定位；型号/IP 先读 find-hosts 技能。等待空闲的预约目标不要求当前已经空闲，不能用空闲筛选排除忙碌机器。固定设备预约先用 get_resources(refresh=false) 核对设备 ID，并按需翻页。数量预约只在设备种类、数量或采样有效性不明时查已有采样。已有采样缺失、失败或过期，且创建或修改设备预约需要有效采样时，只对目标机器补采一次再核对；仍无法确认就说明原因。用户要求多机预约时走下方流程。
3. 创建前用 get_workbench_state(section="reservations") 查看已有预约，按 next_offset 翻页并核对是否重复；默认 overview 不包含预约记录。已知目标时，这个只读检查可与必要的机器定位/设备查询并行。按数量预约传 create_reservation(host_id, mode="count", kind="GPU" 或 "NPU", required_count=数量, minimum_gib=每卡显存 GiB, wait_seconds=持续空闲秒数)。固定卡传 mode="fixed", devices=[真实设备 ID]，不混传数量字段。
4. 用户未指定持续空闲时长可采用工具默认 120 秒，并在结果中说明。email_notify 默认 false；用户要求邮件提醒时先看 get_mail_settings，未配置则引导软件设置，不能索要邮箱授权码。
5. create_reservation 成功后报告真实预约 ID、机器、数量/设备、显存、时长和提醒方式。预约只监测并提醒，不锁卡、不预留硬件、不自动启动训练。
6. 修改使用 update_reservation，只传用户要求改变的字段。取消使用 cancel_reservation。ID 不明确或多个匹配时先查记录，不猜测。
7. 用户要求端口/设备监控时用 create_rule；删除用 delete_rule。不要把规则和预约当成同一条记录。
8. 成功写入返回真实 ID 和完整保存字段时，直接据此报告，不额外读取全工作台。返回不完整、错误、超时或取消时，用 get_workbench_state(section="reservations") 核对预约，用 section="rules" 核对规则，再决定是否重试；不能把响应中断当作未写入，也不盲目重复创建。

## 多机预约

- 先用 `list_group_reservations` 核对重复。指定多台必须同时符合条件，使用 `mode="specified"` 和 `candidate_host_ids`。集群任意几台使用 `mode="cluster_any"`，先通过 `resolve_target`、`get_cluster` 核对集群 ID、revision 和候选机器，再设置 `required_hosts`。两种方式的 `required_devices` 均为每台的设备数。
- 创建时给 `request_id` 唯一值。结果不明先查询，重试相同创建请求时继续使用原值。修改需先读取 `version`。取消保留历史；再次预约使用新的 `request_id`。候选机器必须都在会话允许范围内。
