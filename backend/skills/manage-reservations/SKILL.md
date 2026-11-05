---
name: manage-reservations
description: 用户要求约机器、等待空闲卡、修改或取消预约，以及设置或删除设备监控提醒时使用。支持具体设备和同机设备数量预约。
metadata:
  include_tools: find_hosts get_resources get_workbench_state create_reservation update_reservation cancel_reservation get_mail_settings create_rule delete_rule
---

# 预约和监控

1. 分清用户是查询资源还是要求预约。只有明确要求写入时才创建/修改/取消；不因为找到了空闲卡就自动预约。
2. 复用已核实的 host_id，或用 find_hosts 按别名定位；型号/IP 先读 find-hosts 技能。等待空闲的预约目标不要求当前已经空闲，不能用空闲筛选排除忙碌机器。固定设备预约需 get_resources(refresh=true) 核对设备 ID；数量预约只在型号、设备种类或数量不明时补查。一次预约只能针对一台机器，不跨机器凑卡。
3. 创建前用 get_workbench_state(section="reservations") 查看已有预约，按 next_offset 翻页并核对是否重复；默认 overview 不包含预约记录。已知目标时，这个只读检查可与必要的机器定位/设备查询并行。按数量预约传 create_reservation(host_id, mode="count", kind="GPU" 或 "NPU", required_count=数量, minimum_gib=每卡显存 GiB, wait_seconds=持续空闲秒数)。固定卡传 mode="fixed", devices=[真实设备 ID]，不混传数量字段。
4. 用户未指定持续空闲时长可采用工具默认 120 秒，并在结果中说明。email_notify 默认 false；用户要求邮件提醒时先看 get_mail_settings，未配置则引导软件设置，不能索要邮箱授权码。
5. create_reservation 成功后报告真实预约 ID、机器、数量/设备、显存、时长和提醒方式。预约只监测并提醒，不锁卡、不预留硬件、不自动启动训练。
6. 修改使用 update_reservation，只传用户要求改变的字段。取消使用 cancel_reservation。ID 不明确或多个匹配时先查记录，不猜测。
7. 用户要求端口/设备监控时用 create_rule；删除用 delete_rule。不要把规则和预约当成同一条记录。
8. 成功写入返回真实 ID 和完整保存字段时，直接据此报告，不额外读取全工作台。返回不完整、错误、超时或取消时，用 get_workbench_state(section="reservations") 核对预约，用 section="rules" 核对规则，再决定是否重试；不能把响应中断当作未写入，也不盲目重复创建。
