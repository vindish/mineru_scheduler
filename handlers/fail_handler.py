from handlers.retry_handler import RetryHandler
from db.repository import update_tasks
from task_queue.dlq import DeadLetterQueue
from utils.logger import logger
from db.task_row import TaskRow


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

        for t in tasks:
            try:
                error = (t.last_error or "").lower()

                if "exceeds limit" in error:
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

        if dead_tasks:
            self.dlq.push_batch(dead_tasks, error_type="FATAL")

        if split_tasks:
            for t in split_tasks:
                t.status = "SPLIT_NEEDED"
            update_tasks(split_tasks)
