// Generated from config/internal-defaults.jsonc. DO NOT EDIT. Run node scripts/generate-internal-defaults.mjs
// 单次复制内容大小上限，单位：字节。
export const FILES_COPY_MAX_BYTES = 67108864;
// 单次复制最多包含的文件和目录数。
export const FILES_COPY_MAX_ENTRIES = 1000;
// 普通文件下载上限，单位：字节；与日志下载分别维护。
export const FILES_DOWNLOAD_MAX_BYTES = 536870912;
// 文件夹下载 ZIP 和源文件总量上限，单位：字节。
export const FILES_FOLDER_DOWNLOAD_MAX_BYTES = 536870912;
// 文件夹下载最多扫描/归档的条目数。
export const FILES_FOLDER_DOWNLOAD_MAX_ENTRIES = 10000;
// 文件夹清单的 UTF-8 大小上限，单位：字节。
export const FILES_FOLDER_MANIFEST_MAX_BYTES = 1048576;
// 文件夹上传包总大小上限，单位：字节；包含清单和文件内容。
export const FILES_FOLDER_UPLOAD_MAX_BYTES = 536870912;
// 文件夹上传最多包含的文件和目录数，隐式父目录也计数。
export const FILES_FOLDER_UPLOAD_MAX_ENTRIES = 10000;
// 在线文本编辑和保存上限，单位：字节；超过后使用下载或终端。
export const FILES_TEXT_EDIT_MAX_BYTES = 1048576;
// 单个文件上传上限，单位：字节；后台、客户端和远端接收探针共用。
export const FILES_UPLOAD_MAX_BYTES = 536870912;
// 一次最多导入的服务器行数，不包含表头。
export const IMPORTS_MAX_ROWS = 100;
// 导入 Excel 文件上限，单位：字节。
export const IMPORTS_WORKBOOK_MAX_BYTES = 2097152;
// Excel ZIP 最多包含的归档条目数，防止异常归档。
export const IMPORTS_ZIP_MAX_ENTRIES = 2000;
// Excel ZIP 解压后总量上限，单位：字节。
export const IMPORTS_ZIP_MAX_EXPANDED_BYTES = 16777216;
// 原始训练日志下载上限，单位：字节。
export const LOGS_DOWNLOAD_MAX_BYTES = 536870912;
// 单行日志上限，单位：字节；防止异常长行消耗内存。
export const LOGS_LINE_MAX_BYTES = 65536;
// 日志对比最多读取的原始数据量，单位：字节。
export const LOGS_READ_MAX_BYTES = 67108864;
// 每份日志最多解析的训练记录数。
export const LOGS_READ_MAX_RECORDS = 10000;
// 默认资源刷新间隔，单位：秒；已保存的用户设置优先。
export const MONITORING_REFRESH_INTERVAL_SECONDS = 30;
// 每个技能文件大小上限，单位：UTF-8 字节；工具文本字段同时使用此容量值。
export const SKILLS_FILE_MAX_BYTES = 1048576;
// 技能包最多允许的文件数；解压校验和 MCP schema 同步。
export const SKILLS_MAX_FILES = 128;
// 技能文件解压后总量上限，单位：字节。
export const SKILLS_TOTAL_MAX_BYTES = 8388608;
// 导入技能包大小上限，单位：字节。
export const SKILLS_UPLOAD_MAX_BYTES = 2097152;
// 导入任务正常状态查询间隔，单位：毫秒。
export const UI_IMPORT_POLL_MS = 1000;
// 导入任务查询异常后的重试间隔，单位：毫秒。
export const UI_IMPORT_RETRY_MS = 2500;
// 主界面短提示显示时间，单位：毫秒。
export const UI_NOTICE_DURATION_MS = 7000;
// 高频渲染更新合并延迟，单位：毫秒；不改变采样频率。
export const UI_RENDER_COALESCE_MS = 100;
// 集群预约列表刷新间隔，单位：毫秒。
export const UI_RESERVATION_POLL_MS = 5000;
// 机器服务规则列表刷新间隔，单位：毫秒。
export const UI_SERVICE_POLL_MS = 3000;
// 活动 SSH 隧道状态刷新间隔，单位：毫秒。
export const UI_TUNNEL_POLL_MS = 2000;
