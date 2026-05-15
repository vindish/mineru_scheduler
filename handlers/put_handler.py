import time
from pathlib import Path
from db.repository import update_tasks
from utils.logger import logger
from services.mineru_client import MineruClient, RateLimitError
from db.task_row import TaskRow

class PutHandler:
    def __init__(self, rate_limiter=None):
        self.rate_limiter = rate_limiter
        self.client = MineruClient(rate_limiter=self.rate_limiter)

    def handle_batch(self, tasks: list[TaskRow]):
        updates = []

        for t in tasks:
            tid = None

            try:
                tid = t.id
                path = t.file_path
                url = t.upload_url

                # =========================
                # 🔒 校验
                # =========================
                if not path or not Path(path).exists():
                    raise ValueError(f"file missing: {path}")
                if not url:
                    raise ValueError("upload_url is empty")
                if not url.startswith("http"):
                    raise ValueError(f"invalid upload_url: {url}")
                # =========================
                # 🚀 上传
                # =========================
                self.client.upload_file(url, path)

                t.status = "PUT_DONE"
                t.locked = 0
                updates.append(t)

            except RateLimitError as e:
                wait = max(1.0, float(getattr(e, "retry_after", 0) or 0))
                err = str(e)
                logger.warning(
                    f"[PUT 429] task={tid} cool_down={wait:.1f}s error={err}"
                )
                t.status = "UPLOADED"
                t.next_run_time = time.time() + wait
                t.last_error = f"429 throttled: wait={wait:.1f}s"
                updates.append(t)

            except Exception as e:
                err = str(e)
                transient_keywords = (
                    "timeout",
                    "timed out",
                    "connection reset",
                    "connection refused",
                    "temporarily unavailable",
                    "failed to establish a new connection",
                    "name or service not known",
                    "network is unreachable",
                )
                if any(k in err.lower() for k in transient_keywords):
                    delay = 30.0
                    logger.warning(
                        f"[PUT RETRY] task={tid} delay={delay}s transient error={err}"
                    )
                    t.status = "UPLOADED"
                    t.next_run_time = time.time() + delay
                    t.last_error = err
                    updates.append(t)
                    continue

                logger.error(f"[PUT FAIL] task={tid} error={err}")

                t.status = "FAILED"
                t.last_error = err
                t.locked = 0
                updates.append(t)


        # =========================
        # 📝 批量更新
        # =========================
        if updates:
            update_tasks(updates)

        # =========================
        # ⏱️ 限速
        # =========================