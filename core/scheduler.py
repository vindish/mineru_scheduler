import time
from collections import defaultdict
import traceback
from config.settings import (
    MAX_WORKERS, QPS, FETCH_LIMIT, SCHEDULER_PRIORITY,BATCH_SIZE,QPS_UPLOAD,QPS_PUT,QPS_POLL,QPS_DOWNLOAD,
    UPLOAD_CONCURRENCY, PUT_CONCURRENCY, POLL_CONCURRENCY,FAILED,SPLIT_NEEDED,DOWNLOADING,MAX_FILE_PAGES
)
from db.repository import get_conn,heal_locks
from core.worker_pool import WorkerPool
from core.dispatcher import Dispatcher
from core.rate_limiter import RateLimiter
from core.quota_manager import ApiQuotaManager
from core.watchdog import Watchdog

from db.repository import fetch_runnable_tasks, lock_tasks, unlock_tasks, get_conn
from utils.logger import logger
from PyPDF2 import PdfReader


class Scheduler:

    def __init__(self):
        self.worker_pool = WorkerPool(MAX_WORKERS)
        self.rate_limiter = RateLimiter(QPS)
        # self.dispatcher = Dispatcher(self.rate_limiter)
        self.upload_limiter = RateLimiter(QPS_UPLOAD)
        self.put_limiter = RateLimiter(QPS_PUT)
        self.poll_limiter = RateLimiter(QPS_POLL)
        self.download_limiter = RateLimiter(QPS_DOWNLOAD)
        self.quota_manager = ApiQuotaManager()
        self.dispatcher = Dispatcher(
            rate_limiter = self.rate_limiter,
            upload_limiter=self.upload_limiter,
            put_limiter=self.put_limiter,
            poll_limiter=self.poll_limiter,
            download_limiter=self.download_limiter,
            quota_manager=self.quota_manager
        )
        self.rate_limiter.adjust()
        self.priority = SCHEDULER_PRIORITY

        self.last_heartbeat = 0

        # ✅ Watchdog 只启动一次
        Watchdog().start()

    # =========================
    # 🔥 自动修复
    # =========================
    def _auto_heal_tasks(self):
        unlock, broken = heal_locks(timeout=300)

        logger.info(
            f"[AUTO-HEAL] unlock={unlock} broken={broken}"
        )
        # conn = get_conn()
        # cursor = conn.cursor()

        # now = int(time.time())

        # cursor.execute("""
        #     UPDATE tasks
        #     SET locked=0
        #     WHERE locked=1 AND (? - locked_at > 300)
        # """, (now,))
        # unlock = cursor.rowcount

        # cursor.execute("""
        #     UPDATE tasks
        #     SET locked=0
        #     WHERE locked=1 AND locked_at IS NULL
        # """)
        # broken = cursor.rowcount

        # cursor.execute("""
        #     UPDATE tasks
        #     SET next_run_time=NULL
        #     WHERE next_run_time IS NOT NULL
        #     AND next_run_time < (? - 600)
        # """, (now,))
        # delay = cursor.rowcount

        # conn.commit()

        # if unlock or broken or delay:
        if unlock or broken :
            logger.info(f"[AUTO-HEAL] unlock={unlock} broken={broken}")
            # logger.info(f"[AUTO-HEAL] unlock={unlock} broken={broken} delay={delay}")

    # =========================
    def _group_tasks(self, tasks):
        grouped = defaultdict(list)
        for t in tasks:
            grouped[t.status].append(t)
        return grouped

    def _set_next_run(self, tasks, delay):
        if not tasks:
            return

        now = time.time()
        for t in tasks:
            t.next_run_time = now + max(1.0, delay)
            t.locked = 0
        from db.repository import update_tasks
        update_tasks(tasks)

    def _read_page_count(self, task):
        if getattr(task, "page_count", None):
            return int(task.page_count)

        reader = PdfReader(task.file_path)
        task.page_count = len(reader.pages)
        return int(task.page_count)

    def _prepare_init_tasks(self, tasks):
        ready = []
        split_needed = []
        failed = []

        for task in tasks:
            try:
                pages = self._read_page_count(task)
                if pages > MAX_FILE_PAGES:
                    task.status = "SPLIT_NEEDED"
                    task.last_error = f"page count {pages} exceeds limit {MAX_FILE_PAGES}"
                    split_needed.append(task)
                else:
                    ready.append(task)
            except Exception as e:
                task.status = "FAILED"
                task.last_error = f"read page count failed: {e}"
                failed.append(task)

        updates = split_needed + failed
        if updates:
            from db.repository import update_tasks
            update_tasks(updates)
            logger.info(
                f"[PAGE-CHECK] split_needed={len(split_needed)} failed={len(failed)}"
            )

        allowed, deferred, wait = self.quota_manager.reserve_submission_batch(ready)
        if deferred:
            self._set_next_run(deferred, wait)
            logger.info(
                f"[QUOTA] defer INIT tasks={len(deferred)} wait={wait:.1f}s"
            )

        return allowed




    def run(self):
        logger.info("[LAUNCH] Scheduler 启动")

        empty_rounds = 0

        while True:
            try:
                # self._auto_heal_tasks()

                
                tasks = fetch_runnable_tasks(FETCH_LIMIT)  # Breakpoint

                if not tasks:
                    empty_rounds += 1
                    logger.info("[SCHEDULER] 无可执行任务")

                    if empty_rounds >= 5:
                        logger.warning("[SCHEDULER] 连续空轮询，触发修复")
                        self._auto_heal_tasks()
                        empty_rounds = 0

                    time.sleep(1)
                    continue
                else:
                    empty_rounds = 0

                # =========================
                # 🔒 锁任务
                # =========================
                task_ids = [t.id for t in tasks]
                locked_ids = lock_tasks(task_ids)

                if not locked_ids:
                    time.sleep(0.5)
                    continue

                tasks = [t for t in tasks if t.id in locked_ids]

                grouped = self._group_tasks(tasks)
                dispatched_ids = set()

                logger.info(
                    f"[SCHEDULER] fetched={len(tasks)} "
                    f"locked={len(locked_ids)} "
                    f"queue={self.worker_pool.executor._work_queue.qsize()} "
                    f"qps={self.rate_limiter.qps:.2f}"
                )

                # =========================
                # 🔥 配额控制（关键）
                # =========================
                limit_map = {
                    "FAILED": FAILED,          # 高优先级多给
                    "SPLIT_NEEDED": SPLIT_NEEDED,
                    "DOWNLOADING": DOWNLOADING,
                    "PUT_DONE": POLL_CONCURRENCY,
                    "UPLOADED": PUT_CONCURRENCY,
                    "INIT": UPLOAD_CONCURRENCY
                }

                total_dispatched = 0
                MAX_DISPATCH_PER_ROUND = 100   # 🔥 防止一轮打爆线程池

                # =========================
                # 🔥 无 break + 有序调度
                # =========================
                for status in self.priority:

                    items = [t for t in grouped.get(status, []) if t.status == status]
                    if not items:
                        continue

                    limit = limit_map.get(status, BATCH_SIZE)
                    if isinstance(limit, tuple):
                        limit = limit[0]
                    # logger.info("DEBUG:", status, limit, type(limit))
                    limit = int(max(1, limit))
                    # 👉 限制本轮总投喂量
                    if total_dispatched >= MAX_DISPATCH_PER_ROUND:
                        break

                    # 👉 本状态最多处理多少
                    items = items[:limit]
                    if status == "INIT":
                        items = self._prepare_init_tasks(items)
                        if not items:
                            continue

                    logger.info(f"[DISPATCH] {status} -> {len(items)} tasks")

                    for i in range(0, len(items), BATCH_SIZE):
                        batch = items[i:i + BATCH_SIZE]


                        self.worker_pool.submit(
                            self.dispatcher.dispatch,
                            status,
                            batch
                        )

                        total_dispatched += len(batch)
                        dispatched_ids.update(t.id for t in batch)

                        # 👉 防止线程池爆掉
                        if total_dispatched >= MAX_DISPATCH_PER_ROUND:
                            break

                undispatched_ids = [
                    t.id for t in tasks
                    if t.id not in dispatched_ids and t.status not in ("SPLIT_NEEDED", "FAILED")
                ]
                if undispatched_ids:
                    unlock_tasks(undispatched_ids)

                # =========================
                # 💓 心跳
                # =========================
                now = time.time()
                if now - self.last_heartbeat > 10:
                    quota = self.quota_manager.snapshot()
                    logger.info(
                        f"[HEARTBEAT] queue={self.worker_pool.executor._work_queue.qsize()} "
                        f"qps={self.rate_limiter.qps:.2f} "
                        f"success={self.rate_limiter.success} "
                        f"fail={self.rate_limiter.fail} "
                        f"quota_daily_remaining={quota['daily_remaining']} "
                        f"quota_high_pages_remaining={quota['high_priority_remaining']} "
                        f"quota_minute_tokens={quota['minute_tokens']}"
                    )
                    self.last_heartbeat = now

                self.rate_limiter.adjust()

                time.sleep(0.5)

            except Exception as e:
                logger.error(f"[SCHEDULER ERROR] {e}")
                traceback.print_exc()   # 🔥 必加
                time.sleep(2)
