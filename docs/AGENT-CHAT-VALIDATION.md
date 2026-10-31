# 统一 Agent 对话验证

验证日期：2026-10-31。继续使用本机已有的 GLM-5.3-Flash 配置及系统凭据存储；报告不包含真实机器标识或 API key。

## 真实模型与 SSH

在隔离的临时数据库中复用已保存的模型设置与一台已有免密 NPU 服务器。未修改正式机器配置，未强制重启正式后台。

1. 第一轮要求检查系统并读取 `/etc/os-release` 前 8 行。GLM 实际发出 `ssh_check(system)`、`read_file` 两个原生工具调用，读取成功后返回发行版及架构结论；全轮约 19.8 秒，两次 SSH 各约 3.6 秒。
2. 第二轮要求继续检查刚才那台的 Python 和 torch/vLLM 元数据。模型沿用同一真实目标调用 `ssh_check(environment)`，约 18.0 秒完成，准确限定为当前系统 Python，未把元数据缺失写成所有环境未安装。
3. 另开隔离会话，要求刷新设备资源及占卡情况，并浏览 `/etc` 第一页。模型实际调用 `get_resources(refresh=true)` 和 `read_directory`，成功返回真实 NPU 采样和目录；首次约 29.2 秒，修正目录分页后复测约 27.7 秒。目录结果长时保留下一页位置，并增加逐页读取不重复、不漏项的测试。

本次真实验证没有导入 torch、初始化显卡、写远端文件或启停业务进程。上述耗时是这两轮实测，不能代表所有请求的速度。

## 界面与自动检查

浏览器交互使用独立本地服务、模拟机器及模拟模型，不把演示内容当作真实服务器证据。验证多轮消息、展开工具参数与结果、刷新恢复、取消处理、新建会话及删除确认。工具中模拟的 API_KEY 字段已脱敏，展开结果后页面没有出现原值。

新增检查覆盖原生工具结果续传、会话状态与条件继承、持久恢复、立即取消、已知 key 过滤、JSON 脱敏后仍可解析、读取切片、目录分页、凭据路径拒绝、未知工具/越界机器不执行，以及工具失败反馈给模型。变化记录增加了范围先于分页和计数的回归检查。

模型/会话/接口相关检查 43 项通过；补充范围及目录回归后的对话、模型适配和现有助手检查 28 项通过。前端 167 项通过，TypeScript 检查及生产构建通过。

完整后端检查：468 通过、8 跳过、1 失败；失败仍是已有 `test_password_login_then_provision_and_verify_key[False]`，原因是 Windows 临时 SSH 私钥 ACL，未修改该模块。该次全量检查后补充的范围及目录回归已单独通过。

可复验：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_agent_chat.py tests/test_model_turn.py tests/test_agent_api.py tests/test_infra_assistant.py -q
```

在 `frontend` 执行 `npm.cmd test` 和 `npm.cmd run build`。正式服务加载新后端需正常退出并重开；本次未中断原有终端会话。
