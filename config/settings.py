import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

if load_dotenv:
    load_dotenv()


# =============================================================
# 🔐 凭证
# =============================================================
TOKEN = os.getenv("MINERU_TOKEN")


# =============================================================
# 📁 路径统一配置（输入 / 输出）
# -------------------------------------------------------------
# 所有“PDF 来源目录”和“输出目录”都集中在这里维护：
#   PDF_INPUT_DIRS : 待处理 PDF 的来源（可多个，列表）
#   OUTPUT_BASE_DIR: 所有输出（拆分、下载、解析结果、临时文件）的统一根目录
# 任何子模块都应从本文件读取这些路径，禁止再硬编码。
# 环境变量可覆盖默认值；多目录用英文逗号 ',' 分隔。
# =============================================================

# 项目根目录（settings.py -> config/ -> <项目根>）
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 数据根目录：默认放在项目根/data，便于本地与容器统一
# docker-compose 中通过 BASE_DIR=/app/data 覆盖
BASE_DIR = Path(os.getenv("BASE_DIR") or str(PROJECT_ROOT / "data")).resolve()


def _split_dirs(value: str):
    return [p.strip() for p in (value or "").split(",") if p.strip()]


# -------- 输入 ----------
# 优先 PDF_INPUT_DIRS；兼容旧名 SCAN_DIRS；都没设置则使用 BASE_DIR/pdf
_input_env = os.getenv("PDF_INPUT_DIRS") or os.getenv("SCAN_DIRS")
if _input_env:
    _input_paths = _split_dirs(_input_env)
else:
    _input_paths = [str(BASE_DIR / "pdf")]

# 统一的 PDF 来源列表（绝对路径 Path 对象）
PDF_INPUT_DIRS = [Path(p).expanduser().resolve() for p in _input_paths]

# 兼容旧代码中以字符串列表使用的 SCAN_DIRS
SCAN_DIRS = [str(p) for p in PDF_INPUT_DIRS]

# -------- 输出 ----------
# 所有输出统一挂在 OUTPUT_BASE_DIR 下；单独子项也支持独立覆盖
OUTPUT_BASE_DIR = Path(
    os.getenv("OUTPUT_BASE_DIR") or str(BASE_DIR)
).expanduser().resolve()

DOWNLOAD_DIR = Path(
    os.getenv("DOWNLOAD_DIR") or str(OUTPUT_BASE_DIR / "download")
).expanduser().resolve()

OUTPUT_DIR = Path(
    os.getenv("OUTPUT_DIR") or str(OUTPUT_BASE_DIR / "output")
).expanduser().resolve()

SPLIT_DIR = Path(
    os.getenv("SPLIT_DIR") or str(OUTPUT_BASE_DIR / "split")
).expanduser().resolve()

TEMP_DIR = Path(
    os.getenv("TEMP_DIR") or str(OUTPUT_BASE_DIR / "temp")
).expanduser().resolve()

LOG_DIR = Path(
    os.getenv("LOG_DIR") or str(BASE_DIR / "logs")
).expanduser().resolve()

# 启动期保证“输出类”目录存在（不存在则创建；已存在不会报错）
# ⚠️ 注意：PDF_INPUT_DIRS 是“输入”，绝对不要在这里 mkdir。
# 否则在容器里、NAS 还没挂上时会创建一个本地空目录，
# 既扫不出文件，又会屏蔽后续真实挂载。
for _d in (BASE_DIR, OUTPUT_BASE_DIR, DOWNLOAD_DIR, OUTPUT_DIR,
           SPLIT_DIR, TEMP_DIR, LOG_DIR):
    _d.mkdir(parents=True, exist_ok=True)


# =============================================================
# 🌐 MinerU API
# =============================================================
UPLOAD_URL = "https://mineru.net/api/v4/file-urls/batch"
POLL_URL = "https://mineru.net/api/v4/extract-results/batch/"


# =============================================================
# 🗄️ PostgreSQL
# =============================================================
DATABASE_URL = os.getenv("DATABASE_URL")
PG_CONN_KWARGS = {
    "host": os.getenv("POSTGRES_HOST", "postgres"),
    "port": int(os.getenv("POSTGRES_PORT", "5432")),
    "dbname": os.getenv("POSTGRES_DB", "mineru_scheduler"),
    "user": os.getenv("POSTGRES_USER", "mineru"),
    "password": os.getenv("POSTGRES_PASSWORD", "mineru_password"),
}


# =============================================================
# 📊 官方频控（2026-04-15 18:00 生效）
# =============================================================
DAILY_FILE_LIMIT = int(os.getenv("MINERU_DAILY_FILE_LIMIT", "5000"))
MAX_FILE_PAGES = int(os.getenv("MINERU_MAX_FILE_PAGES", "200"))
HIGH_PRIORITY_DAILY_PAGE_LIMIT = int(
    os.getenv("MINERU_HIGH_PRIORITY_DAILY_PAGE_LIMIT", "1000")
)
SUBMIT_FILE_RATE_PER_MINUTE = int(
    os.getenv("MINERU_SUBMIT_FILE_RATE_PER_MINUTE", "50")
)


# =============================================================
# ⚙️ 并发控制
# =============================================================
MAX_WORKERS = 12
QPS = 0.8
QPS_UPLOAD = 0.8
QPS_PUT = 0.8
QPS_POLL = 0.8
QPS_DOWNLOAD = 1.0

# 每轮调度各状态投喂上限
UPLOAD_CONCURRENCY = 50
PUT_CONCURRENCY = 30
POLL_CONCURRENCY = 20
FAILED = 5
SPLIT_NEEDED = 5
DOWNLOADING = 20


# =============================================================
# 🧮 调度
# =============================================================
FETCH_LIMIT = 200
BATCH_SIZE = 50
WATCHDOG_INTERVAL = 60


# =============================================================
# 🔁 重试
# =============================================================
RETRY_DELAY = 60
MAX_RETRY = 5


# =============================================================
# 🔍 扫描
# =============================================================
SCAN_INTERVAL = 60          # 基础扫描间隔（秒）
SCAN_MAX_FILES = 200000     # 每次最多扫描多少文件（防止卡死）
SCAN_BATCH_SLEEP = 0.01     # 扫描过程中微暂停（防 CPU 飙升）

# 扫描水位线（回压控制，避免一次性把 NAS 上的几十万 PDF 全塞进库）
# 队列“在跑/待跑”的任务数 > HIGH 时，scan 暂停一轮
# 队列“在跑/待跑”的任务数 < LOW 时，恢复扫描
SCAN_BACKLOG_HIGH = 2000
SCAN_BACKLOG_LOW = 500


SCHEDULER_PRIORITY = [
    "FAILED",
    "SPLIT_NEEDED",
    "DOWNLOADING",
    "PUT_DONE",
    "UPLOADED",
    "INIT",
]


VALID_TRANSITIONS = {
    "INIT": ["INIT", "UPLOADED", "SPLIT_NEEDED", "FAILED"],
    "UPLOADED": ["UPLOADED", "PUT_DONE", "FAILED"],
    "PUT_DONE": ["PUT_DONE", "DOWNLOADING", "FAILED"],
    # DOWNLOADING -> DOWNLOADING：用于网络抖动/限流“原地等待重下”，
    # 不再回到 INIT 浪费 API 配额
    "DOWNLOADING": ["DOWNLOADING", "DOWNLOADED", "FAILED"],
    "DOWNLOADED": ["DOWNLOADED"],
    "FAILED": ["FAILED", "SPLIT_NEEDED", "INIT", "DEAD"],
    "SPLIT_NEEDED": ["SPLIT_NEEDED", "SPLIT_DONE", "FAILED", "DEAD"],
    "SPLIT_DONE": ["SPLIT_DONE"],
    "DEAD": ["DEAD"],
}


INIT_SQL = """
CREATE TABLE IF NOT EXISTS tasks (
    id BIGSERIAL PRIMARY KEY,
    file_path TEXT,
    file_name TEXT,
    status TEXT,
    api_task_id TEXT,
    upload_url TEXT,
    zip_url TEXT,
    retry_count INTEGER DEFAULT 0,
    max_retry INTEGER DEFAULT 5,
    next_run_time DOUBLE PRECISION,
    locked INTEGER DEFAULT 0,
    locked_at BIGINT,
    last_error TEXT,
    error_type TEXT,
    parent_id BIGINT,
    dead_at DOUBLE PRECISION,
    page_count INTEGER,
    created_at DOUBLE PRECISION,
    updated_at DOUBLE PRECISION
);

CREATE INDEX IF NOT EXISTS idx_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_locked ON tasks(locked);
CREATE INDEX IF NOT EXISTS idx_next_run ON tasks(next_run_time);
CREATE UNIQUE INDEX IF NOT EXISTS idx_file_path ON tasks(file_path);
CREATE INDEX IF NOT EXISTS idx_parent_id ON tasks(parent_id);

CREATE TABLE IF NOT EXISTS api_quota_usage (
    quota_date TEXT PRIMARY KEY,
    daily_files INTEGER DEFAULT 0,
    high_priority_pages INTEGER DEFAULT 0,
    updated_at DOUBLE PRECISION
);
"""


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
