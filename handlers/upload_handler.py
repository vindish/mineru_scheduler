import json
import time
import random
from pathlib import Path

from db.repository import update_tasks
from config.settings import TOKEN,UPLOAD_URL
from utils.logger import logger
import os
from services.mineru_client import MineruClient
from db.task_row import TaskRow


# logger.info("UPLOAD FILE PATH:", __file__)



class UploadHandler:
    def __init__(self, rate_limiter=None):
        self.rate_limiter = rate_limiter
        self.client = MineruClient(rate_limiter=self.rate_limiter)

    def handle_batch(self, tasks: list[TaskRow]):
        logger.info(f"[UPLOAD] start batch={len(tasks)}")
        logger.info(f"[UPLOAD] batch={len(tasks)}")

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
                    "data_id": str(tid)
                })

                valid.append(t)

            except Exception as e:
                err = str(e)

                t.status = "FAILED"
                t.last_error = err
                t.locked = 0
                updates.append(t)


        if not files:
            if updates:
                update_tasks(updates)
            return

        # =========================
        # 2. 调 API
        # =========================
        try:

            
            data = self.client.create_upload_batch(files)
            # logger.info("UPLOAD data =", data)
            # logger.info(f"[UPLOAD] {data}")

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
                tid = t.id


                t.status = "UPLOADED"
                t.api_task_id = batch_id
                t.upload_url = urls[i]
                t.locked = 0
                updates.append(t)


        except Exception as e:
            err = str(e)

            logger.error(f"[UPLOAD ERROR] {err}")
            logger.info("[UPLOAD ERROR]", err)
            for t in valid:
                tid = t.id

                t.status = "FAILED"
                t.last_error = err
                t.locked = 0
                if "expired" in err:
                    t.status = "INIT"
                    t.upload_url = None   # 强制重新获取
                updates.append(t)

        # =========================
        # 4. 统一回写
        # =========================
        if updates:
            update_tasks(updates)

        logger.info(f"[UPLOAD] done update={len(updates)}")