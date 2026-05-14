import time
from pathlib import Path
from threading import Semaphore

from db.repository import update_tasks
from utils.logger import logger
from services.mineru_client import MineruClient, RateLimitError
from services.storage import Storage
from db.task_row import TaskRow


# 本地致命错误（与 MinerU 无关）；命中即进 DEAD，绝不重新走 INIT/UPLOAD
LOCAL_FATAL_KEYWORDS = (
    "errno 36",
    "file name too long",
    "errno 28",
    "no space left",
    "errno 13",
    "permission denied",
    "errno 30",
    "read-only file system",
)


def _is_local_fatal(err: str) -> bool:
    e = err.lower()
    return any(k in e for k in LOCAL_FATAL_KEYWORDS)


class DownloadHandler:
    """
    下载处理器：
        - 成功            → DOWNLOADED
        - 本地致命（写盘） → DEAD（直接进 DLQ，不再消耗 API 配额）
        - 限流 / 抖动     → 保持 DOWNLOADING，只推 next_run_time，下轮再下
        - 其他            → FAILED（交 FailHandler 兜底）
    """

    # 抖动重试默认退避
    DEFAULT_RETRY_DELAY = 30
    MAX_DOWNLOAD_RETRIES = 8

    def __init__(self, rate_limiter=None, max_concurrency=3):
        self.rate_limiter = rate_limiter
        self.storage = Storage()
        self.dir = self.storage.download_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self.sem = Semaphore(max_concurrency)
        self.client = MineruClient(rate_limiter=self.rate_limiter)

    def handle_batch(self, tasks: list[TaskRow]):
        if not tasks:
            return

        logger.info(f"[DOWNLOAD] batch={len(tasks)}")

        updates = []

        for t in tasks:
            try:
                url = t.zip_url
                file_name = t.file_name
                file_path = t.file_path

                if not url:
                    raise ValueError("EMPTY_DOWNLOAD_URL")

                path = self.storage.get_download_path(
                    file_name=file_name,
                    task_id=None,
                    file_path=file_path,
                )

                # 已存在且足够大 → 直接 DOWNLOADED
                if self.storage.exists(path):
                    size = self.storage.size(path)
                    if size > 1024:
                        logger.info(f"[DOWNLOAD] skip exists: {path.name}")
                        t.status = "DOWNLOADED"
                        updates.append(t)
                        continue
                    logger.warning(f"[DOWNLOAD] bad file, re-download: {path.name}")
                    self.storage.remove(path)

                with self.sem:
                    if self.rate_limiter:
                        self.rate_limiter.acquire()
                    resp = self.client.download_stream(url)
                    self.storage.save_stream(resp, path)

                t.status = "DOWNLOADED"
                t.last_error = None
                updates.append(t)
                logger.info(f"[DOWNLOAD OK] {path.name}")

            except RateLimitError as e:
                wait = max(1.0, float(getattr(e, "retry_after", 0) or 0))
                logger.warning(
                    f"[DOWNLOAD 429] task={t.id} cool_down={wait:.1f}s -> stay DOWNLOADING"
                )
                # 不消耗 retry_count，状态保持 DOWNLOADING
                t.status = "DOWNLOADING"
                t.next_run_time = time.time() + wait
                t.last_error = f"429 throttled: wait={wait:.1f}s"
                updates.append(t)

            except Exception as e:
                err = str(e)

                # 本地致命：直接 DEAD，不要再让它回到 INIT 浪费 API 额度
                if _is_local_fatal(err):
                    logger.error(
                        f"[DOWNLOAD FATAL] task={t.id} -> DEAD (local) error={err[:200]}"
                    )
                    # 通过 FAILED → DEAD 的合法迁移路径
                    t.status = "FAILED"
                    t.last_error = err[:500]
                    t.error_type = "LOCAL_FATAL"
                    updates.append(t)
                    continue

                # 抖动类：保持 DOWNLOADING，下轮直接重下，不重新 upload
                retry_count = int(getattr(t, "retry_count", 0) or 0)
                if retry_count < self.MAX_DOWNLOAD_RETRIES:
                    delay = self.DEFAULT_RETRY_DELAY * max(1, retry_count + 1)
                    logger.warning(
                        f"[DOWNLOAD RETRY] task={t.id} attempt={retry_count + 1} "
                        f"delay={delay}s error={err[:200]}"
                    )
                    t.status = "DOWNLOADING"
                    t.next_run_time = time.time() + delay
                    t.retry_count = retry_count + 1
                    t.last_error = err[:500]
                    updates.append(t)
                    continue

                # 重试用尽 → FAILED 让 FailHandler 处置
                logger.error(f"[DOWNLOAD FAIL] task={t.id} error={err[:200]}")
                t.status = "FAILED"
                t.last_error = err[:500]
                updates.append(t)

        if updates:
            update_tasks(updates)
