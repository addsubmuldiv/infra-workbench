// Allowed keys and reviewed bounds; application values live only in config/internal-defaults.json.
export const SCHEMA = {
  "files": {
    "upload_max_bytes": {
      "min": 1,
      "max": 536870912,
      "frontend": true
    },
    "folder_upload_max_bytes": {
      "min": 1,
      "max": 536870912,
      "frontend": true
    },
    "folder_upload_max_entries": {
      "min": 1,
      "max": 10000,
      "frontend": true
    },
    "folder_manifest_max_bytes": {
      "min": 1,
      "max": 1048576,
      "frontend": true
    },
    "download_max_bytes": {
      "min": 1,
      "max": 536870912,
      "frontend": true
    },
    "folder_download_max_bytes": {
      "min": 1,
      "max": 536870912,
      "frontend": true
    },
    "folder_download_max_entries": {
      "min": 1,
      "max": 10000,
      "frontend": true
    },
    "text_edit_max_bytes": {
      "min": 1,
      "max": 1048576,
      "frontend": true
    },
    "copy_max_bytes": {
      "min": 1,
      "max": 67108864,
      "frontend": true
    },
    "copy_max_entries": {
      "min": 1,
      "max": 1000,
      "frontend": true
    }
  },
  "logs": {
    "download_max_bytes": {
      "min": 1,
      "max": 536870912,
      "frontend": true
    },
    "read_max_bytes": {
      "min": 1,
      "max": 67108864,
      "frontend": true
    },
    "read_max_records": {
      "min": 1,
      "max": 10000,
      "frontend": true
    },
    "line_max_bytes": {
      "min": 1,
      "max": 65536,
      "frontend": true
    }
  },
  "imports": {
    "workbook_max_bytes": {
      "min": 1,
      "max": 2097152,
      "frontend": true
    },
    "max_rows": {
      "min": 1,
      "max": 100,
      "frontend": true
    },
    "zip_max_entries": {
      "min": 1,
      "max": 2000,
      "frontend": true
    },
    "zip_max_expanded_bytes": {
      "min": 1,
      "max": 16777216,
      "frontend": true
    }
  },
  "skills": {
    "upload_max_bytes": {
      "min": 1,
      "max": 2097152,
      "frontend": true
    },
    "total_max_bytes": {
      "min": 1,
      "max": 8388608,
      "frontend": true
    },
    "file_max_bytes": {
      "min": 1,
      "max": 1048576,
      "frontend": true
    },
    "max_files": {
      "min": 1,
      "max": 128,
      "frontend": true
    }
  },
  "ssh": {
    "connect_timeout_seconds": {
      "min": 1,
      "max": 604800,
      "frontend": false
    },
    "jump_extra_timeout_seconds": {
      "min": 1,
      "max": 604800,
      "frontend": false
    },
    "collection_timeout_seconds": {
      "min": 1,
      "max": 604800,
      "frontend": false
    },
    "keepalive_interval_seconds": {
      "min": 1,
      "max": 604800,
      "frontend": false
    },
    "keepalive_count_max": {
      "min": 1,
      "max": 100000,
      "frontend": false
    }
  },
  "transfers": {
    "concurrency": {
      "min": 1,
      "max": 100000,
      "frontend": false
    },
    "max_jobs": {
      "min": 1,
      "max": 100000,
      "frontend": false
    },
    "idle_expiry_seconds": {
      "min": 1,
      "max": 604800,
      "frontend": false
    },
    "send_timeout_seconds": {
      "min": 1,
      "max": 604800,
      "frontend": false
    }
  },
  "history": {
    "changes_retention_days": {
      "min": 1,
      "max": 365,
      "frontend": false
    },
    "changes_max_events": {
      "min": 1,
      "max": 100000,
      "frontend": false
    },
    "resources_retention_days": {
      "min": 1,
      "max": 365,
      "frontend": false
    }
  },
  "assistant": {
    "context_fallback_tokens": {
      "min": 1,
      "max": 1000000,
      "frontend": false
    },
    "metadata_success_cache_seconds": {
      "min": 1,
      "max": 604800,
      "frontend": false
    },
    "metadata_failure_cache_seconds": {
      "min": 1,
      "max": 604800,
      "frontend": false
    },
    "metadata_timeout_seconds": {
      "min": 1,
      "max": 604800,
      "frontend": false
    }
  },
  "notifications": {
    "max_age_seconds": {
      "min": 1,
      "max": 604800,
      "frontend": false
    }
  },
  "ui": {
    "reservation_poll_ms": {
      "min": 1,
      "max": 60000,
      "frontend": true
    },
    "service_poll_ms": {
      "min": 1,
      "max": 60000,
      "frontend": true
    },
    "tunnel_poll_ms": {
      "min": 1,
      "max": 60000,
      "frontend": true
    },
    "import_poll_ms": {
      "min": 1,
      "max": 60000,
      "frontend": true
    },
    "import_retry_ms": {
      "min": 1,
      "max": 60000,
      "frontend": true
    },
    "notice_duration_ms": {
      "min": 1,
      "max": 60000,
      "frontend": true
    },
    "render_coalesce_ms": {
      "min": 1,
      "max": 60000,
      "frontend": true
    }
  }
};

// Independent SSH scripts receive generated constants without importing the local backend.
export const PROBES = {};
