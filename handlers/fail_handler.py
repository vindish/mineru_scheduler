from handlers.retry_handler import RetryHandler
from db.repository import update_tasks
from task_queue.dlq import DeadLetterQueue
from utils.logger import logger
from db.task_row import TaskRow


class FailHandler:
    """
    失败分流处理器（核心调度层）
    """

    def __init__(self, rate_limiter=None):
        self.retry_handler = RetryHandler()
        self.dlq = DeadLetterQueue()
        self.rate_limiter = rate_limiter

    def handle_batch(self, tasks: list[TaskRow]):
        if not tasks:
            return

        logger.info(f"[FAIL] batch={len(tasks)}")
        logger.info(f"[FAIL] batch={len(tasks)}")

        retry_tasks = []
        split_tasks = []
        dead_tasks = []

        for t in tasks:
            try:
                # ❗统一 TaskRow，不再支持 dict
                error = (t.last_error or "").lower()

                if "exceeds limit" in error:
                    split_tasks.append(t)

                elif "file not found" in error or "invalid pdf" in error:
                    dead_tasks.append(t)

                elif "429" in error:
                    retry_tasks.append(t)
                else:
                    retry_tasks.append(t)

            except Exception as e:
                logger.error(f"[FAIL_HANDLER ERROR] {e}")
                dead_tasks.append(t)

        # 🔁 retry
        if retry_tasks:
            self.retry_handler.handle_batch(retry_tasks)

        # ☠️ dead
        if dead_tasks:
            self.dlq.push_batch(dead_tasks, error_type="FATAL")

        # ✂️ split
        if split_tasks:
            for t in split_tasks:
                t.status = "SPLIT_NEEDED"

            update_tasks(split_tasks)