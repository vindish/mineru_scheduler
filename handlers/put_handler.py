import time
from pathlib import Path
from db.repository import update_tasks
from utils.logger import logger
from services.mineru_client import MineruClient
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
                path  = t.file_path
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
                # logger.info(f"[PUT CHECK] task={tid} path={path}")
                # =========================
                # 🚀 上传
                # =========================
                self.client.upload_file(url, path)

                t.status = "PUT_DONE"
                t.locked = 0
                updates.append(t)


            except Exception as e:
                err = str(e)

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