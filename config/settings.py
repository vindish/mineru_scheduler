import os
from pathlib import Path

LOG_DIR = Path("data/logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)

# ========= 基础配置 =========
# TOKEN = ""
TOKEN = os.getenv("MINERU_TOKEN")

UPLOAD_URL = "https://mineru.net/api/v4/file-urls/batch" 
# API_URL = "https://mineru.net/api/v4/file-urls/batch"

# POLL_URL =  f"https://mineru.net/api/v4/extract-results/batch/{batch_id}"
POLL_URL =  f"https://mineru.net/api/v4/extract-results/batch/"


BASE_DIR = r"data"
# SPLIT_DIR = r"data\split"
DB_NAME="tasks1.db"

SCAN_DIRS = [
    "data/pdf",
    # "pdf_extra",
    # "pdf_history"
]


# ========= 并发控制 =========
MAX_WORKERS = 7
QPS = 0.8
QPS_UPLOAD=0.8
QPS_PUT=0.8
QPS_POLL=0.5
QPS_DOWNLOAD=0.83
# =========================
# 🔥 配额控制（关键）
# =========================
UPLOAD_CONCURRENCY = 10
PUT_CONCURRENCY = 200
POLL_CONCURRENCY = 200
FAILED = 20
SPLIT_NEEDED = 30
DOWNLOADING = 10


# ========= 调度 =========
FETCH_LIMIT = 500
BATCH_SIZE = 50
WATCHDOG_INTERVAL = 60


# ========= 重试 =========
RETRY_DELAY = 60
MAX_RETRY = 5


# ========= 扫描配置 =========
SCAN_INTERVAL = 60          # 基础扫描间隔（秒）
SCAN_MAX_FILES = 200000      # 每次最多扫描多少文件（防止卡死）
SCAN_BATCH_SLEEP = 0.01    # 扫描过程中微暂停（防CPU飙升）

SCHEDULER_PRIORITY = [
                "FAILED",
                "SPLIT_NEEDED",
                "DOWNLOADING",
                "PUT_DONE",
                "UPLOADED",
                "INIT"
            ]


VALID_TRANSITIONS = {
    "INIT": ["INIT","UPLOADED", "FAILED"],
    "UPLOADED": ["PUT_DONE", "FAILED"],
    "PUT_DONE": [ "DOWNLOADING","FAILED","PUT_DONE"],
    # "POLLING": ["DOWNLOADING", "FAILED", "POLLING","PUT_DONE"],
    "DOWNLOADING": ["DOWNLOADED", "FAILED"],
    # "DONE": ["DOWNLOADED"],
    "FAILED": ["SPLIT_NEEDED","INIT", "DEAD","FAILED"],
    "SPLIT_NEEDED": ["SPLIT_DONE","FAILED"],
    # "SPLIT_DONE": ["INIT"],    
}


INIT_SQL = """
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT,
    file_name TEXT,
    status TEXT,
    api_task_id TEXT,
    upload_url TEXT,
    zip_url TEXT,
    retry_count INTEGER DEFAULT 0,
    max_retry INTEGER DEFAULT 5,
    next_run_time REAL,
    locked INTEGER DEFAULT 0,
    locked_at INTEGER,
    last_error TEXT,
    error_type TEXT,
    parent_id INTEGER,
    dead_at REAL,
    created_at REAL,
    updated_at REAL
);

CREATE INDEX IF NOT EXISTS idx_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_locked ON tasks(locked);
CREATE INDEX IF NOT EXISTS idx_next_run ON tasks(next_run_time);
CREATE UNIQUE INDEX IF NOT EXISTS idx_file_path ON tasks(file_path);
CREATE INDEX IF NOT EXISTS idx_parent_id ON tasks(parent_id);
"""
# CREATE INDEX IF NOT EXISTS idx_file_path ON tasks(file_path);

TASK_COLUMNS = [
    "id",
    "file_path",
    "file_name",
    "status",
    "api_task_id",
    "upload_url",
    "zip_url",
    "retry_count",
    "max_retry",
    "next_run_time",
    "locked",
    "locked_at",
    "last_error",
    "error_type",
    "dead_at",
    "created_at",
    "updated_at",
]
