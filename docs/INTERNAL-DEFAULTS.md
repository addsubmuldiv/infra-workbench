# 内部策略维护

`config/internal-defaults.jsonc` 是内部策略的唯一数值来源；应用版本继续使用 `version.json`。配置不是用户设置，不从数据目录或环境变量加载，也没有热更新。

```sh
node scripts/generate-internal-defaults.mjs
node scripts/generate-internal-defaults.mjs --check
```

修改 JSON 后生成并提交 Python、TypeScript 和独立探针中的生成区；前端修改后重新构建 dist，桌面分发需重建安装包。源码 Python 和安装版无需 Node。CI 先检查已提交产物，再自动生成，避免漏提交被掩盖。生成缺失会使启动失败，不退回另一份默认数字。

容量和数量上限的 schema 最大值设为迁移前的现有保护上限；仅修改 JSON 可以降低上限，扩大上限需要同时审查 schema、内存/磁盘/解压成本与边界测试。普通时间预算和保留策略允许在 schema 的明确范围内调整。单位/协议/业务规则不属于此配置。

HTTP、内置助手、外部 MCP 复用原服务校验；前端只是提前提示。旧前端提示可能与新后台不同，后台拒绝时返回实际限制。用户保存的偏好继续优先；演示只使用静态前端常量，不访问真实 API。

生成器校验所有字段后再写入，单个文件通过临时文件替换；不保证多文件事务性，中断后重新生成并运行 `--check`。所有生成文件提交版本控制。

## 参数表

键名带 `_bytes` 为字节，`_seconds` 为秒，`_ms` 为毫秒，`_days` 为天，其余为计数或 token 数。分组对应文件容量、日志、导入、技能、SSH、传输、历史、助手、通知、界面；不同业务即使当前值相同也分别维护。

| 键 | 当前值 |
|---|---|
| `files.upload_max_bytes` | 536870912 |
| `files.folder_upload_max_bytes` | 536870912 |
| `files.folder_upload_max_entries` | 10000 |
| `files.folder_manifest_max_bytes` | 1048576 |
| `files.download_max_bytes` | 536870912 |
| `files.folder_download_max_bytes` | 536870912 |
| `files.folder_download_max_entries` | 10000 |
| `files.text_edit_max_bytes` | 1048576 |
| `files.copy_max_bytes` | 67108864 |
| `files.copy_max_entries` | 1000 |
| `logs.download_max_bytes` | 536870912 |
| `logs.read_max_bytes` | 67108864 |
| `logs.read_max_records` | 10000 |
| `logs.line_max_bytes` | 65536 |
| `imports.workbook_max_bytes` | 2097152 |
| `imports.max_rows` | 100 |
| `imports.zip_max_entries` | 2000 |
| `imports.zip_max_expanded_bytes` | 16777216 |
| `skills.upload_max_bytes` | 2097152 |
| `skills.total_max_bytes` | 8388608 |
| `skills.file_max_bytes` | 1048576 |
| `skills.max_files` | 128 |
| `ssh.connect_timeout_seconds` | 20 |
| `ssh.jump_extra_timeout_seconds` | 20 |
| `ssh.collection_timeout_seconds` | 35 |
| `ssh.keepalive_interval_seconds` | 60 |
| `ssh.keepalive_count_max` | 3 |
| `transfers.concurrency` | 2 |
| `transfers.max_jobs` | 32 |
| `transfers.idle_expiry_seconds` | 600 |
| `transfers.send_timeout_seconds` | 600 |
| `history.changes_retention_days` | 7 |
| `history.changes_max_events` | 10000 |
| `history.resources_retention_days` | 30 |
| `assistant.context_fallback_tokens` | 32000 |
| `assistant.metadata_success_cache_seconds` | 3600 |
| `assistant.metadata_failure_cache_seconds` | 60 |
| `assistant.metadata_timeout_seconds` | 8 |
| `notifications.max_age_seconds` | 120 |
| `ui.reservation_poll_ms` | 5000 |
| `ui.service_poll_ms` | 3000 |
| `ui.tunnel_poll_ms` | 2000 |
| `ui.import_poll_ms` | 1000 |
| `ui.import_retry_ms` | 2500 |
| `ui.notice_duration_ms` | 7000 |
| `ui.render_coalesce_ms` | 100 |

资源新鲜度、预约判断、更新器退出/恢复、跨平台启动链、布局与协议常量保留在原模块。整改设计见 [实施方案](superpowers/plans/2026-11-05-internal-defaults.md)。
