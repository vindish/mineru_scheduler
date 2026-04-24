from pathlib import Path
from threading import Semaphore

from db.repository import update_tasks
from utils.logger import logger
from services.mineru_client import MineruClient
from services.storage import Storage
from db.task_row import TaskRow


class DownloadHandler:
    """
    下载处理器（稳定 + 高性能版）
    """

    def __init__(self, rate_limiter=None, max_concurrency=3):
        self.rate_limiter = rate_limiter

        # ✅ 单例 storage（避免重复创建）
        self.storage = Storage()

        # ✅ 下载目录
        self.dir = self.storage.download_dir
        self.dir.mkdir(parents=True, exist_ok=True)

        # ✅ 并发控制（可调）
        self.sem = Semaphore(max_concurrency)

        # ✅ API client
        self.client = MineruClient(rate_limiter=self.rate_limiter)

    # =========================
    # 🔽 核心处理
    # =========================
    def handle_batch(self, tasks: list[TaskRow]):
        if not tasks:
            return

        logger.info(f"[DOWNLOAD] batch={len(tasks)}")

        updates = []

        for t in tasks:
            try:
                tid = t.id
                url = t.zip_url
                file_name = t.file_name
                file_path = t.file_path

                # =========================
                # 🔒 基础校验
                # =========================
                if not url:
                    raise ValueError("EMPTY_DOWNLOAD_URL")

                # =========================
                # 📁 生成路径（统一规范）
                # =========================
                path = self.storage.get_download_path(
                    file_name=file_name,
                    task_id=None,
                    file_path=file_path
                )

                # =========================
                # ♻️ 已存在文件处理（避免重复下载）
                # =========================
                if self.storage.exists(path):
                    size = self.storage.size(path)

                    # 👉 小于1KB基本判定为坏文件
                    if size > 1024:
                        logger.info(f"[DOWNLOAD] skip exists: {path.name}")
                        t.status = "DOWNLOADED"
                        updates.append(t)
                        continue
                    else:
                        logger.warning(f"[DOWNLOAD] bad file, re-download: {path.name}")
                        self.storage.remove(path)

                # =========================
                # 🚀 下载（带并发 + 限速）
                # =========================
                with self.sem:

                    # 👉 限速（关键）
                    if self.rate_limiter:
                        self.rate_limiter.acquire()

                    resp = self.client.download_stream(url)

                    # 👉 流写入（自动分块）
                    self.storage.save_stream(resp, path)

                # =========================
                # ✅ 成功
                # =========================
                t.status = "DOWNLOADED"
                t.last_error = None
                updates.append(t)

                logger.info(f"[DOWNLOAD OK] {path.name}")

            except Exception as e:
                err = str(e)

                logger.error(f"[DOWNLOAD FAIL] task={t.id} error={err}")

                # =========================
                # ❌ 失败处理
                # =========================
                t.status = "FAILED"
                t.last_error = err[:500]   # 防止日志爆炸
                updates.append(t)

        # =========================
        # 📝 批量更新
        # =========================
        if updates:
            update_tasks(updates)