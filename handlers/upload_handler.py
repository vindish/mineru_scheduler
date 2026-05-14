import time
from pathlib import Path

from db.repository import update_tasks
from config.settings import TOKEN, UPLOAD_URL  # noqa: F401  保留兼容
from utils.logger import logger
from services.mineru_client import MineruClient, RateLimitError
from db.task_row import TaskRow


class UploadHandler:
    def __init__(self, rate_limiter=None, quota_manager=None):
        self.rate_limiter = rate_limiter
        self.quota_manager = quota_manager
        self.client = MineruClient(rate_limiter=self.rate_limiter)

    def handle_batch(self, tasks: list[TaskRow]):
        logger.info(f"[UPLOAD] start batch={len(tasks)}")

        files = []
        valid = []
        updates = []

        # =========================
        # 1. 构建请求
        # =========================
        for t in tasks:
            try:
                tid = t.id
                path = t.file_path

                if not path or not Path(path).exists():
                    raise ValueError(f"file missing: {path}")

                files.append({
                    "name": Path(path).name,
                    "data_id": str(tid),
                })
                valid.append(t)

            except Exception as e:
                err = str(e)
                t.status = "FAILED"
                t.last_error = err
                t.locked = 0
                updates.append(t)

        if not files:
            if self.quota_manager and tasks:
                self.quota_manager.release_reservations(tasks)
            if updates:
                update_tasks(updates)
            return

        invalid = [t for t in tasks if t not in valid]
        if invalid and self.quota_manager:
            self.quota_manager.release_reservations(invalid)

        # =========================
        # 2. 调 API
        # =========================
        try:
            data = self.client.create_upload_batch(files)
            if data.get("code") != 0:
                raise RuntimeError(data.get("msg"))

            data_block = data.get("data") or {}
            batch_id = data_block.get("batch_id")
            urls = data_block.get("file_urls", [])

            if len(urls) != len(valid):
                raise RuntimeError("url count mismatch")

            # =========================
            # 3. 成功回写
            # =========================
            for i, t in enumerate(valid):
                t.status = "UPLOADED"
                t.api_task_id = batch_id
                t.upload_url = urls[i]
                t.locked = 0
                updates.append(t)

            if self.quota_manager:
                self.quota_manager.commit_reservations(valid)

        except RateLimitError as e:
            # 429: 不是“失败”，是“被限流”。把 quota 释放掉，
            # 任务保持 INIT，next_run_time 推到冷却结束之后再试
            wait = max(1.0, float(getattr(e, "retry_after", 0) or 0))
            logger.warning(
                f"[UPLOAD 429] cooling down={wait:.1f}s tasks={len(valid)} -> defer to INIT"
            )
            if self.quota_manager:
                self.quota_manager.release_reservations(valid)
            now = time.time()
            for t in valid:
                t.status = "INIT"
                t.upload_url = None
                t.next_run_time = now + wait
                t.last_error = f"429 throttled: wait={wait:.1f}s"
                t.locked = 0
                updates.append(t)

        except Exception as e:
            err = str(e)
            logger.error(f"[UPLOAD ERROR] {err}")
            if self.quota_manager:
                self.quota_manager.release_reservations(valid)
            for t in valid:
                t.status = "FAILED"
                t.last_error = err
                t.locked = 0
                # token 过期 → 重新拿 upload_url
                if "expired" in err.lower():
                    t.status = "INIT"
                    t.upload_url = None
                updates.append(t)

        # =========================
        # 4. 统一回写
        # =========================
        if updates:
            update_tasks(updates)

        logger.info(f"[UPLOAD] done update={len(updates)}")
