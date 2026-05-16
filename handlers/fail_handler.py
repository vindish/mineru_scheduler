import time

from handlers.retry_handler import RetryHandler
from db.repository import update_tasks
from task_queue.dlq import DeadLetterQueue
from utils.logger import logger
from db.task_row import TaskRow
from handlers.upload_handler import is_daily_limit_error


# 临时性错误关键字（命中即走重试）
TRANSIENT_KEYWORDS = (
    "429",
    "throttled",
    "too many requests",
    "ratelimit",
    "rate limit",
    "timed out",
    "timeout",
    "connection reset",
    "connection refused",
    "temporarily unavailable",
    "503",
    "502",
    "504",
)

# 致命错误关键字（命中即进入 DLQ）
FATAL_KEYWORDS = (
    "file not found",
    "invalid pdf",
    "pdf_invalid",
    # 本地写盘致命，与 MinerU API 无关，不应再消耗配额
    "errno 36",
    "file name too long",
    "errno 28",
    "no space left",
    "errno 13",
    "permission denied",
    "errno 30",
    "read-only file system",
)


class FailHandler:
    """
    失败分流处理器：
        - 临时性 → RetryHandler（指数退避回 INIT）
        - 致命   → DLQ
        - 超页   → SPLIT_NEEDED
    """

    def __init__(self, rate_limiter=None):
        self.retry_handler = RetryHandler()
        self.dlq = DeadLetterQueue()
        self.rate_limiter = rate_limiter

    def handle_batch(self, tasks: list[TaskRow]):
        if not tasks:
            return

        logger.info(f"[FAIL] batch={len(tasks)}")

        retry_tasks = []
        split_tasks = []
        dead_tasks = []
        quota_tasks = []

        for t in tasks:
            try:
                error = (t.last_error or "").lower()

                if is_daily_limit_error(error):
                    quota_tasks.append(t)
                elif "exceeds limit" in error:
                    split_tasks.append(t)
                elif any(k in error for k in FATAL_KEYWORDS):
                    dead_tasks.append(t)
                elif any(k in error for k in TRANSIENT_KEYWORDS):
                    retry_tasks.append(t)
                else:
                    # 默认按可重试处理（保守）
                    retry_tasks.append(t)

            except Exception as e:
                logger.error(f"[FAIL_HANDLER ERROR] {e}")
                dead_tasks.append(t)

        if retry_tasks:
            self.retry_handler.handle_batch(retry_tasks)

        if quota_tasks:
            now = time.time()
            delay = 6 * 60 * 60
            for t in quota_tasks:
                t.status = "INIT"
                t.next_run_time = now + delay
                t.error_type = "API_DAILY_LIMIT"
                t.locked = 0
            update_tasks(quota_tasks)

        if dead_tasks:
            self.dlq.push_batch(dead_tasks, error_type="FATAL")

        if split_tasks:
            for t in split_tasks:
                t.status = "SPLIT_NEEDED"
            update_tasks(split_tasks)
