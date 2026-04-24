from pathlib import Path
from db.repository import update_tasks
from utils.logger import logger
from services.mineru_client import MineruClient
from services.storage import Storage
from db.task_row import TaskRow
from threading import Semaphore



class DownloadHandler:
    def __init__(self, rate_limiter=None):

        self.rate_limiter = rate_limiter
        self.storage = Storage()
        storage = Storage()
        self.output_dir = storage.output_dir
        self.dir = output_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self.sem = Semaphore(2)
        self.client = MineruClient(rate_limiter=self.rate_limiter)


    def handle_batch(self, tasks: list[TaskRow]):
        logger.info(f"[DOWNLOAD] batch={len(tasks)}")
        logger.info(f"[DOWNLOAD] batch={len(tasks)}")
        updates = []
        
        for t in tasks:
            try:

                tid = t.id
                url = t.zip_url
                file_name = t.file_name
                file_path = t.file_path

                if not url:
                    raise ValueError("empty zip url")

                # path = self.dir / f"{file_name}.zip"
                storage = Storage()

                path = storage.get_download_path(file_name, task_id=None,file_path=file_path)

                if storage.exists(path):
                    logger.info("已存在，跳过")
                else:
                    with self.sem:
                        
                        resp = self.client.download_stream(url)
                        storage.save_stream(resp, path)

                t.status = "DOWNLOADED"
                updates.append(t)

            except Exception as e:
                t.status = "FAILED"
                t.last_error = str(e)
                updates.append(t)

        update_tasks(updates)