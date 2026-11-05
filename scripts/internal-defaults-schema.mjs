// Allowed keys and reviewed bounds; application values live only in config/internal-defaults.json.
export const SCHEMA = {
  "files": {
    "upload_max_bytes": {
      "min": 1,
      "max": 536870912,
      "frontend": true,
      "description": "单个文件上传上限，单位：字节；后台、客户端和远端接收探针共用。"
    },
    "folder_upload_max_bytes": {
      "min": 1,
      "max": 536870912,
      "frontend": true,
      "description": "文件夹上传包总大小上限，单位：字节；包含清单和文件内容。"
    },
    "folder_upload_max_entries": {
      "min": 1,
      "max": 10000,
      "frontend": true,
      "description": "文件夹上传最多包含的文件和目录数，隐式父目录也计数。"
    },
    "folder_manifest_max_bytes": {
      "min": 1,
      "max": 1048576,
      "frontend": true,
      "description": "文件夹清单的 UTF-8 大小上限，单位：字节。"
    },
    "download_max_bytes": {
      "min": 1,
      "max": 536870912,
      "frontend": true,
      "description": "普通文件下载上限，单位：字节；与日志下载分别维护。"
    },
    "folder_download_max_bytes": {
      "min": 1,
      "max": 536870912,
      "frontend": true,
      "description": "文件夹下载 ZIP 和源文件总量上限，单位：字节。"
    },
    "folder_download_max_entries": {
      "min": 1,
      "max": 10000,
      "frontend": true,
      "description": "文件夹下载最多扫描/归档的条目数。"
    },
    "text_edit_max_bytes": {
      "min": 1,
      "max": 1048576,
      "frontend": true,
      "description": "在线文本编辑和保存上限，单位：字节；超过后使用下载或终端。"
    },
    "copy_max_bytes": {
      "min": 1,
      "max": 67108864,
      "frontend": true,
      "description": "单次复制内容大小上限，单位：字节。"
    },
    "copy_max_entries": {
      "min": 1,
      "max": 1000,
      "frontend": true,
      "description": "单次复制最多包含的文件和目录数。"
    }
  },
  "logs": {
    "download_max_bytes": {
      "min": 1,
      "max": 536870912,
      "frontend": true,
      "description": "原始训练日志下载上限，单位：字节。"
    },
    "read_max_bytes": {
      "min": 1,
      "max": 67108864,
      "frontend": true,
      "description": "日志对比最多读取的原始数据量，单位：字节。"
    },
    "read_max_records": {
      "min": 1,
      "max": 10000,
      "frontend": true,
      "description": "每份日志最多解析的训练记录数。"
    },
    "line_max_bytes": {
      "min": 1,
      "max": 65536,
      "frontend": true,
      "description": "单行日志上限，单位：字节；防止异常长行消耗内存。"
    }
  },
  "imports": {
    "workbook_max_bytes": {
      "min": 1,
      "max": 2097152,
      "frontend": true,
      "description": "导入 Excel 文件上限，单位：字节。"
    },
    "max_rows": {
      "min": 1,
      "max": 100,
      "frontend": true,
      "description": "一次最多导入的服务器行数，不包含表头。"
    },
    "zip_max_entries": {
      "min": 1,
      "max": 2000,
      "frontend": true,
      "description": "Excel ZIP 最多包含的归档条目数，防止异常归档。"
    },
    "zip_max_expanded_bytes": {
      "min": 1,
      "max": 16777216,
      "frontend": true,
      "description": "Excel ZIP 解压后总量上限，单位：字节。"
    },
    "sheet_max_rows": {
      "min": 1,
      "max": 1000,
      "frontend": false,
      "description": "工作表最多数据行数，不含表头，包含空行。"
    },
    "sheet_max_columns": {
      "min": 4,
      "max": 32,
      "frontend": false,
      "description": "工作表最大列数，包括未识别列。"
    }
  },
  "skills": {
    "upload_max_bytes": {
      "min": 1,
      "max": 2097152,
      "frontend": true,
      "description": "导入技能包大小上限，单位：字节。"
    },
    "total_max_bytes": {
      "min": 1,
      "max": 8388608,
      "frontend": true,
      "description": "技能文件解压后总量上限，单位：字节。"
    },
    "file_max_bytes": {
      "min": 1,
      "max": 1048576,
      "frontend": true,
      "description": "每个技能文件大小上限，单位：UTF-8 字节；工具文本字段同时使用此容量值。"
    },
    "max_files": {
      "min": 1,
      "max": 128,
      "frontend": true,
      "description": "技能包最多允许的文件数；解压校验和 MCP schema 同步。"
    }
  },
  "ssh": {
    "connect_timeout_seconds": {
      "min": 1,
      "max": 604800,
      "frontend": false,
      "description": "SSH 默认连接预算，单位：秒；保留现有 SSH 配置覆盖优先级。"
    },
    "jump_extra_timeout_seconds": {
      "min": 1,
      "max": 604800,
      "frontend": false,
      "description": "跳板连接追加预算，单位：秒；不表示每一跳都重复追加。"
    },
    "collection_timeout_seconds": {
      "min": 1,
      "max": 604800,
      "frontend": false,
      "description": "远端资源采集命令超时，单位：秒；不用于任意用户长任务。"
    },
    "keepalive_interval_seconds": {
      "min": 1,
      "max": 604800,
      "frontend": false,
      "description": "SSH 保活间隔，单位：秒；不覆盖现有显式 SSH 配置。"
    },
    "keepalive_count_max": {
      "min": 1,
      "max": 100000,
      "frontend": false,
      "description": "连续保活无响应的次数上限。"
    }
  },
  "transfers": {
    "concurrency": {
      "min": 1,
      "max": 100000,
      "frontend": false,
      "description": "后台最多并行处理的上传任务数；不是状态队列容量。"
    },
    "max_jobs": {
      "min": 1,
      "max": 100000,
      "frontend": false,
      "description": "最多保留的上传任务数；优先回收已完成任务。"
    },
    "idle_expiry_seconds": {
      "min": 1,
      "max": 604800,
      "frontend": false,
      "description": "非活动传输任务保留时间，单位：秒；进行中任务不按此规则清理。"
    },
    "send_timeout_seconds": {
      "min": 1,
      "max": 604800,
      "frontend": false,
      "description": "上传发送与远端验证阶段预算，单位：秒。"
    }
  },
  "history": {
    "changes_retention_days": {
      "min": 1,
      "max": 365,
      "frontend": false,
      "description": "资源变化事件保留天数；不改变资源新鲜度规则。"
    },
    "changes_max_events": {
      "min": 1,
      "max": 100000,
      "frontend": false,
      "description": "资源变化事件最多保留条数。"
    },
    "resources_retention_days": {
      "min": 1,
      "max": 365,
      "frontend": false,
      "description": "资源观测历史保留天数；过期/未知判断仍由业务规则处理。"
    }
  },
  "assistant": {
    "context_fallback_tokens": {
      "min": 1,
      "max": 1000000,
      "frontend": false,
      "description": "无法取得模型容量且用户未手填时的默认上下文，单位：token。"
    },
    "metadata_success_cache_seconds": {
      "min": 1,
      "max": 604800,
      "frontend": false,
      "description": "成功获取模型容量的缓存时间，单位：秒；按模型和凭据身份隔离。"
    },
    "metadata_failure_cache_seconds": {
      "min": 1,
      "max": 604800,
      "frontend": false,
      "description": "模型容量查询失败后缓存默认值的时间，单位：秒。"
    },
    "metadata_timeout_seconds": {
      "min": 1,
      "max": 604800,
      "frontend": false,
      "description": "模型容量元数据查询总预算，单位：秒；不占满聊天回复超时。"
    }
  },
  "notifications": {
    "max_age_seconds": {
      "min": 1,
      "max": 604800,
      "frontend": false,
      "description": "通知最大有效期，单位：秒；超过后不补发陈旧通知。"
    }
  },
  "ui": {
    "reservation_poll_ms": {
      "min": 1,
      "max": 60000,
      "frontend": true,
      "description": "集群预约列表刷新间隔，单位：毫秒。"
    },
    "service_poll_ms": {
      "min": 1,
      "max": 60000,
      "frontend": true,
      "description": "机器服务规则列表刷新间隔，单位：毫秒。"
    },
    "tunnel_poll_ms": {
      "min": 1,
      "max": 60000,
      "frontend": true,
      "description": "活动 SSH 隧道状态刷新间隔，单位：毫秒。"
    },
    "import_poll_ms": {
      "min": 1,
      "max": 60000,
      "frontend": true,
      "description": "导入任务正常状态查询间隔，单位：毫秒。"
    },
    "import_retry_ms": {
      "min": 1,
      "max": 60000,
      "frontend": true,
      "description": "导入任务查询异常后的重试间隔，单位：毫秒。"
    },
    "notice_duration_ms": {
      "min": 1,
      "max": 60000,
      "frontend": true,
      "description": "主界面短提示显示时间，单位：毫秒。"
    },
    "render_coalesce_ms": {
      "min": 1,
      "max": 60000,
      "frontend": true,
      "description": "高频渲染更新合并延迟，单位：毫秒；不改变采样频率。"
    }
  }
};

// Independent SSH scripts receive generated constants without importing the local backend.
export const PROBES = {
  "backend/file_ops.py": {
    "TEXT_LIMIT": "FILES_TEXT_EDIT_MAX_BYTES",
    "COPY_LIMIT": "FILES_COPY_MAX_BYTES",
    "ENTRY_LIMIT": "FILES_COPY_MAX_ENTRIES"
  },
  "backend/file_upload_probe.py": {
    "MAX_UPLOAD": "FILES_UPLOAD_MAX_BYTES"
  },
  "backend/folder_upload_probe.py": {
    "MAX_UPLOAD": "FILES_FOLDER_UPLOAD_MAX_BYTES",
    "MAX_MANIFEST": "FILES_FOLDER_MANIFEST_MAX_BYTES",
    "MAX_ENTRIES": "FILES_FOLDER_UPLOAD_MAX_ENTRIES"
  },
  "backend/folder_download_probe.py": {
    "MAX_SIZE": "FILES_FOLDER_DOWNLOAD_MAX_BYTES",
    "MAX_ENTRIES": "FILES_FOLDER_DOWNLOAD_MAX_ENTRIES"
  },
  "backend/log_reader.py": {
    "MAX_BYTES": "LOGS_READ_MAX_BYTES",
    "MAX_RECORDS": "LOGS_READ_MAX_RECORDS",
    "MAX_LINE": "LOGS_LINE_MAX_BYTES"
  },
  "backend/log_download_probe.py": {
    "MAX_DOWNLOAD": "LOGS_DOWNLOAD_MAX_BYTES",
    "MAX_FILE_DOWNLOAD": "FILES_DOWNLOAD_MAX_BYTES"
  }
};
