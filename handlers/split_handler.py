# handlers/split_handler.py

from db.repository import update_tasks, insert_tasks
from utils.logger import logger
from services.storage import Storage
from services.pdf_splitter import PDFSplitter
from db.task_row import TaskRow
from pathlib import Path


class SplitHandler:

    def __init__(self, rate_limiter=None, max_pages=200):
        self.rate_limiter = rate_limiter
        self.storage = Storage()
        self.splitter = PDFSplitter(self.storage,
                                     max_pages,
                                     rate_limiter=self.rate_limiter)

    def handle_batch(self, tasks: list[TaskRow]):
        logger.info(f"[SPLIT] batch={len(tasks)}")

        success_updates = []
        failed_updates = []
        new_tasks = []

        for t in tasks:
            if t.status != "SPLIT_NEEDED":
                continue
            try:
                parts = self.splitter.split(t.file_path)

                # 不需要拆分
                if len(parts) == 1:
                    t.status = "SPLIT_DONE"
                    success_updates.append(t)
                    continue

                # 子任务（去重）
                for p in parts:
                    new_tasks.append(TaskRow({
                        "file_path": p,
                        "file_name": Path(p).name,
                        "status": "INIT",
                        "parent_id": t.id
                    }))

                t.status = "SPLIT_DONE"
                success_updates.append(t)

            except Exception as e:
                msg = str(e)

                if "PDF_INVALID" in msg:
                    t.status = "DEAD"
                elif "decrypt" in msg:
                    t.status = "DEAD"
                else:
                    t.status = "FAILED"

                t.last_error = msg
                failed_updates.append(t)

        # 去重插入
        if new_tasks:
            seen = set()
            unique = []
            for t in new_tasks:
                key = (t.file_path, t.parent_id)
                if key not in seen:
                    seen.add(key)
                    unique.append(t)

            insert_tasks(unique)

        if success_updates:
            update_tasks(success_updates)

        if failed_updates:
            update_tasks(failed_updates)