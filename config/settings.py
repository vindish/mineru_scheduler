import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

if load_dotenv:
    load_dotenv()
TOKEN = os.getenv("MINERU_TOKEN")

LOG_DIR = Path("data/logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)

# ========= 基础配置 =========
# TOKEN = ""
# TOKEN = os.getenv("MINERU_TOKEN")

UPLOAD_URL = "https://mineru.net/api/v4/file-urls/batch" 
# API_URL = "https://mineru.net/api/v4/file-urls/batch"

# POLL_URL =  f"https://mineru.net/api/v4/extract-results/batch/{batch_id}"
POLL_URL =  f"https://mineru.net/api/v4/extract-results/batch/"


BASE_DIR = r"/mnt/nas/downloadBT/code_Project/quiz_taskrow_system/scheduler_system/data"
# SPLIT_DIR = r"data\split"
DB_NAME="tasks1.db"

SCAN_DIRS = [
    "/mnt/nas/downloadBT/code_Project/quiz_taskrow_system/scheduler_system/data/pdf",
    # "pdf_extra",
    # "pdf_history"
]


# ========= 官方频控策略（2026-04-15 18:00 生效） =========
DAILY_FILE_LIMIT = int(os.getenv("MINERU_DAILY_FILE_LIMIT", "5000"))
MAX_FILE_PAGES = int(os.getenv("MINERU_MAX_FILE_PAGES", "200"))
HIGH_PRIORITY_DAILY_PAGE_LIMIT = int(os.getenv("MINERU_HIGH_PRIORITY_DAILY_PAGE_LIMIT", "1000"))
SUBMIT_FILE_RATE_PER_MINUTE = int(os.getenv("MINERU_SUBMIT_FILE_RATE_PER_MINUTE", "50"))


# ========= 并发控制 =========
MAX_WORKERS = 12
QPS = 2.0
QPS_UPLOAD=1.0
QPS_PUT=10.0
QPS_POLL=15.0
QPS_DOWNLOAD=5.0
# =========================
# 🔥 配额控制（关键）
# =========================
UPLOAD_CONCURRENCY = 50
PUT_CONCURRENCY = 30
POLL_CONCURRENCY = 20
FAILED = 5
SPLIT_NEEDED = 5
DOWNLOADING = 20


# ========= 调度 =========
FETCH_LIMIT = 200
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
    "INIT": ["INIT","UPLOADED", "SPLIT_NEEDED", "FAILED"],
    "UPLOADED": ["PUT_DONE", "FAILED"],
    "PUT_DONE": [ "DOWNLOADING","FAILED","PUT_DONE"],
    # "POLLING": ["DOWNLOADING", "FAILED", "POLLING","PUT_DONE"],
    "DOWNLOADING": ["DOWNLOADED", "FAILED"],
    # "DONE": ["DOWNLOADED"],
    "FAILED": ["SPLIT_NEEDED","INIT", "DEAD","FAILED"],
    "SPLIT_NEEDED": ["SPLIT_DONE","FAILED","DEAD"],
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
    page_count INTEGER,
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
    "parent_id",
    "dead_at",
    "page_count",
    "created_at",
    "updated_at",
]
