# Generated from config/internal-defaults.jsonc. DO NOT EDIT. Run node scripts/generate-internal-defaults.mjs
# 无法取得模型容量且用户未手填时的默认上下文，单位：token。
ASSISTANT_CONTEXT_FALLBACK_TOKENS = 524288
# 模型容量查询失败后缓存默认值的时间，单位：秒。
ASSISTANT_METADATA_FAILURE_CACHE_SECONDS = 60
# 成功获取模型容量的缓存时间，单位：秒；按模型和凭据身份隔离。
ASSISTANT_METADATA_SUCCESS_CACHE_SECONDS = 3600
# 模型容量元数据查询总预算，单位：秒；不占满聊天回复超时。
ASSISTANT_METADATA_TIMEOUT_SECONDS = 8
# 单次复制内容大小上限，单位：字节。
FILES_COPY_MAX_BYTES = 67108864
# 单次复制最多包含的文件和目录数。
FILES_COPY_MAX_ENTRIES = 1000
# 普通文件下载上限，单位：字节；与日志下载分别维护。
FILES_DOWNLOAD_MAX_BYTES = 536870912
# 文件夹下载 ZIP 和源文件总量上限，单位：字节。
FILES_FOLDER_DOWNLOAD_MAX_BYTES = 536870912
# 文件夹下载最多扫描/归档的条目数。
FILES_FOLDER_DOWNLOAD_MAX_ENTRIES = 10000
# 文件夹清单的 UTF-8 大小上限，单位：字节。
FILES_FOLDER_MANIFEST_MAX_BYTES = 1048576
# 文件夹上传包总大小上限，单位：字节；包含清单和文件内容。
FILES_FOLDER_UPLOAD_MAX_BYTES = 536870912
# 文件夹上传最多包含的文件和目录数，隐式父目录也计数。
FILES_FOLDER_UPLOAD_MAX_ENTRIES = 10000
# 在线文本编辑和保存上限，单位：字节；超过后使用下载或终端。
FILES_TEXT_EDIT_MAX_BYTES = 1048576
# 单个文件上传上限，单位：字节；后台、客户端和远端接收探针共用。
FILES_UPLOAD_MAX_BYTES = 536870912
# 资源变化事件最多保留条数。
HISTORY_CHANGES_MAX_EVENTS = 10000
# 资源变化事件保留天数；不改变资源新鲜度规则。
HISTORY_CHANGES_RETENTION_DAYS = 7
# 资源观测历史保留天数；过期/未知判断仍由业务规则处理。
HISTORY_RESOURCES_RETENTION_DAYS = 30
# 一次最多导入的服务器行数，不包含表头。
IMPORTS_MAX_ROWS = 100
# 工作表最大列数，包括未识别列。
IMPORTS_SHEET_MAX_COLUMNS = 32
# 工作表最多数据行数，不含表头，包含空行。
IMPORTS_SHEET_MAX_ROWS = 1000
# 导入 Excel 文件上限，单位：字节。
IMPORTS_WORKBOOK_MAX_BYTES = 2097152
# Excel ZIP 最多包含的归档条目数，防止异常归档。
IMPORTS_ZIP_MAX_ENTRIES = 2000
# Excel ZIP 解压后总量上限，单位：字节。
IMPORTS_ZIP_MAX_EXPANDED_BYTES = 16777216
# 原始训练日志下载上限，单位：字节。
LOGS_DOWNLOAD_MAX_BYTES = 536870912
# 单行日志上限，单位：字节；防止异常长行消耗内存。
LOGS_LINE_MAX_BYTES = 65536
# 日志对比最多读取的原始数据量，单位：字节。
LOGS_READ_MAX_BYTES = 67108864
# 每份日志最多解析的训练记录数。
LOGS_READ_MAX_RECORDS = 10000
# 通知最大有效期，单位：秒；超过后不补发陈旧通知。
NOTIFICATIONS_MAX_AGE_SECONDS = 120
# 每个技能文件大小上限，单位：UTF-8 字节；工具文本字段同时使用此容量值。
SKILLS_FILE_MAX_BYTES = 1048576
# 技能包最多允许的文件数；解压校验和 MCP schema 同步。
SKILLS_MAX_FILES = 128
# 技能文件解压后总量上限，单位：字节。
SKILLS_TOTAL_MAX_BYTES = 8388608
# 导入技能包大小上限，单位：字节。
SKILLS_UPLOAD_MAX_BYTES = 2097152
# 远端资源采集命令超时，单位：秒；不用于任意用户长任务。
SSH_COLLECTION_TIMEOUT_SECONDS = 35
# AsyncSSH 未配置 ConnectTimeout 时的回退预算，单位：秒；OpenSSH 监控与跳板子进程保留各自原有预算。
SSH_CONNECT_TIMEOUT_SECONDS = 20
# 跳板连接追加预算，单位：秒；不表示每一跳都重复追加。
SSH_JUMP_EXTRA_TIMEOUT_SECONDS = 20
# 连续保活无响应的次数上限。
SSH_KEEPALIVE_COUNT_MAX = 3
# SSH 保活间隔，单位：秒；不覆盖现有显式 SSH 配置。
SSH_KEEPALIVE_INTERVAL_SECONDS = 60
# 后台最多并行处理的上传任务数；不是状态队列容量。
TRANSFERS_CONCURRENCY = 2
# 非活动传输任务保留时间，单位：秒；进行中任务不按此规则清理。
TRANSFERS_IDLE_EXPIRY_SECONDS = 600
# 最多保留的上传任务数；优先回收已完成任务。
TRANSFERS_MAX_JOBS = 32
# 上传发送与远端验证阶段预算，单位：秒。
TRANSFERS_SEND_TIMEOUT_SECONDS = 600
# 导入任务正常状态查询间隔，单位：毫秒。
UI_IMPORT_POLL_MS = 1000
# 导入任务查询异常后的重试间隔，单位：毫秒。
UI_IMPORT_RETRY_MS = 2500
# 主界面短提示显示时间，单位：毫秒。
UI_NOTICE_DURATION_MS = 7000
# 高频渲染更新合并延迟，单位：毫秒；不改变采样频率。
UI_RENDER_COALESCE_MS = 100
# 集群预约列表刷新间隔，单位：毫秒。
UI_RESERVATION_POLL_MS = 5000
# 机器服务规则列表刷新间隔，单位：毫秒。
UI_SERVICE_POLL_MS = 3000
# 活动 SSH 隧道状态刷新间隔，单位：毫秒。
UI_TUNNEL_POLL_MS = 2000

def format_bytes(value):
    for unit, size in (("GiB", 1024**3), ("MiB", 1024**2), ("KiB", 1024)):
        if value >= size and value % size == 0: return str(value // size) + " " + unit
    return str(value) + " B"
