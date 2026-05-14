import errno
import time
from pathlib import Path
from threading import Semaphore

from db.repository import update_tasks
from utils.logger import logger
from services.mineru_client import MineruClient, RateLimitError
from services.storage import Storage
from db.task_row import TaskRow


# 真正“无可挽回”的本地致命错误（命中即 DEAD，不再消耗 API 配额）
LOCAL_FATAL_KEYWORDS = (
    "errno 28",       # ENOSPC No space left
    "no space left",
    "errno 13",       # EACCES Permission denied
    "permission denied",
    "errno 30",       # EROFS Read-only file system
    "read-only file system",
)

# 文件名/路径过长：先尝试逐级缩短文件名，全部失败再 DEAD
NAME_TOO_LONG_KEYWORDS = (
    "errno 36",
    "file name too long",
)


def _is_local_fatal(err: str) -> bool:
    e = err.lower()
    return any(k in e for k in LOCAL_FATAL_KEYWORDS)


def _is_name_too_long(err: str) -> bool:
    e = err.lower()
    return any(k in e for k in NAME_TOO_LONG_KEYWORDS)


def _save_with_retry(storage: Storage, client: MineruClient, url: str,
                     file_name=None, task_id=None, file_path=None):
    """
    依次尝试不同长度的文件名，遇到 ENAMETOOLONG 自动缩短。
    返回 (path, used_shortening: bool)；其它错误向上抛。
    """
    last_err = None
    candidates = list(storage.shortened_download_paths(
        file_name=file_name, task_id=task_id, file_path=file_path
    ))

    for idx, path in enumerate(candidates):
        try:
            resp = client.download_stream(url)
            storage.save_stream(resp, path)
            return path, idx > 0
        except OSError as e:
            # ENAMETOOLONG / 文件名过长才继续缩短，其他错误立即抛出
            if e.errno == errno.ENAMETOOLONG or _is_name_too_long(str(e)):
                last_err = e
                logger.warning(
                    f"[DOWNLOAD] name too long at len={len(path.name)} "
                    f"({path.name[:60]}...), 尝试更短的文件名"
                )
                # 写到一半的残留文件清掉
                try:
                    if path.exists():
                        path.unlink(missing_ok=True)
                except OSError:
                    pass
                continue
            raise

    # 所有候选都失败，只能抛最后那个 ENAMETOOLONG，让上层判 DEAD
    if last_err is None:
        last_err = OSError(errno.ENAMETOOLONG, "unable to find a writable short filename")
    raise last_err


class DownloadHandler:
    """
    下载处理器：
        - 成功                     → DOWNLOADED
        - 文件名过长 → 自动缩短重试 → 仍失败才 DEAD
        - 其他本地致命（写盘）       → DEAD（直接进 DLQ，不再消耗 API 配额）
        - 限流 / 抖动               → 保持 DOWNLOADING，只推 next_run_time，下轮再下
        - 其他                      → FAILED（交 FailHandler 兜底）
    """

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

                # 已存在且足够大 → 直接 DOWNLOADED
                primary = self.storage.get_download_path(
                    file_name=file_name, task_id=None, file_path=file_path
                )
                if self.storage.exists(primary):
                    size = self.storage.size(primary)
                    if size > 1024:
                        logger.info(f"[DOWNLOAD] skip exists: {primary.name}")
                        t.status = "DOWNLOADED"
                        updates.append(t)
                        continue
                    logger.warning(f"[DOWNLOAD] bad file, re-download: {primary.name}")
                    self.storage.remove(primary)

                with self.sem:
                    if self.rate_limiter:
                        self.rate_limiter.acquire()
                    saved_path, shortened = _save_with_retry(
                        self.storage, self.client, url,
                        file_name=file_name, file_path=file_path,
                    )

                t.status = "DOWNLOADED"
                t.last_error = None
                updates.append(t)
                if shortened:
                    logger.info(f"[DOWNLOAD OK] shortened name: {saved_path.name}")
                else:
                    logger.info(f"[DOWNLOAD OK] {saved_path.name}")

            except RateLimitError as e:
                wait = max(1.0, float(getattr(e, "retry_after", 0) or 0))
                logger.warning(
                    f"[DOWNLOAD 429] task={t.id} cool_down={wait:.1f}s -> stay DOWNLOADING"
                )
                t.status = "DOWNLOADING"
                t.next_run_time = time.time() + wait
                t.last_error = f"429 throttled: wait={wait:.1f}s"
                updates.append(t)

            except Exception as e:
                err = str(e)

                # 文件名过长且 _save_with_retry 也救不了 → DEAD
                if _is_name_too_long(err):
                    logger.error(
                        f"[DOWNLOAD FATAL NAME] task={t.id} -> DEAD "
                        f"(filename impossible to shorten) error={err[:200]}"
                    )
                    t.status = "FAILED"
                    t.last_error = err[:500]
                    t.error_type = "LOCAL_FATAL"
                    updates.append(t)
                    continue

                # 其他本地致命 → DEAD
                if _is_local_fatal(err):
                    logger.error(
                        f"[DOWNLOAD FATAL] task={t.id} -> DEAD (local) error={err[:200]}"
                    )
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

                logger.error(f"[DOWNLOAD FAIL] task={t.id} error={err[:200]}")
                t.status = "FAILED"
                t.last_error = err[:500]
                updates.append(t)

        if updates:
            update_tasks(updates)
