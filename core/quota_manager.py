import math
import time
from datetime import datetime, timedelta
from threading import Lock

from config.settings import (
    DAILY_FILE_LIMIT,
    HIGH_PRIORITY_DAILY_PAGE_LIMIT,
    SUBMIT_FILE_RATE_PER_MINUTE,
)
from db.repository import get_conn
from utils.logger import logger


class ApiQuotaManager:
    """
    Local guardrail for MinerU submission limits.

    Daily usage is persisted in PostgreSQL; minute-level throttling is an in-memory
    token bucket because it only needs to protect the current process.
    """

    def __init__(
        self,
        daily_file_limit=DAILY_FILE_LIMIT,
        high_priority_page_limit=HIGH_PRIORITY_DAILY_PAGE_LIMIT,
        submit_file_rate_per_minute=SUBMIT_FILE_RATE_PER_MINUTE,
    ):
        self.daily_file_limit = int(daily_file_limit)
        self.high_priority_page_limit = int(high_priority_page_limit)
        self.submit_file_rate_per_minute = float(submit_file_rate_per_minute)
        self.lock = Lock()

        self.capacity = max(1.0, self.submit_file_rate_per_minute)
        self.refill_per_second = self.submit_file_rate_per_minute / 60.0
        self.tokens = self.capacity
        self.last_refill = time.time()

        self.pending = {}
        self._ensure_schema()

    def _ensure_schema(self):
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS api_quota_usage (
                quota_date TEXT PRIMARY KEY,
                daily_files INTEGER DEFAULT 0,
                high_priority_pages INTEGER DEFAULT 0,
                updated_at REAL
            )
            """
        )
        conn.commit()

    def _quota_date(self):
        return datetime.now().strftime("%Y-%m-%d")

    def _seconds_until_next_day(self):
        now = datetime.now()
        tomorrow = datetime(now.year, now.month, now.day) + timedelta(days=1)
        return max(1.0, (tomorrow - now).total_seconds())

    def _usage(self):
        conn = get_conn()
        quota_date = self._quota_date()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT daily_files, high_priority_pages
            FROM api_quota_usage
            WHERE quota_date=%s
            """,
            (quota_date,),
        )
        row = cursor.fetchone()
        if row:
            return int(row["daily_files"] or 0), int(row["high_priority_pages"] or 0)
        return 0, 0

    def _pending_totals(self):
        files = len(self.pending)
        high_pages = sum(v[1] for v in self.pending.values())
        return files, high_pages

    def _refill(self):
        now = time.time()
        elapsed = max(0.0, now - self.last_refill)
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_per_second)
        self.last_refill = now

    def reserve_submission_batch(self, tasks):
        """
        Reserve as many tasks as possible without exceeding daily or rolling
        minute file limits. Returns (allowed, deferred, wait_seconds).
        """
        if not tasks:
            return [], [], 0.0

        with self.lock:
            self._refill()
            used_files, used_high_pages = self._usage()
            pending_files, pending_high_pages = self._pending_totals()

            remaining_daily = self.daily_file_limit - used_files - pending_files
            minute_slots = int(math.floor(self.tokens))
            allowed_count = min(len(tasks), remaining_daily, minute_slots)

            if allowed_count <= 0:
                if remaining_daily <= 0:
                    return [], list(tasks), self._seconds_until_next_day()

                needed = 1.0 - self.tokens
                wait = needed / self.refill_per_second if self.refill_per_second else 60.0
                return [], list(tasks), max(1.0, wait)

            allowed = list(tasks[:allowed_count])
            deferred = list(tasks[allowed_count:])
            self.tokens -= allowed_count

            high_remaining = max(
                0,
                self.high_priority_page_limit - used_high_pages - pending_high_pages,
            )
            for task in allowed:
                pages = int(getattr(task, "page_count", None) or 1)
                high_pages = min(high_remaining, pages)
                high_remaining -= high_pages
                self.pending[task.id] = (1, high_pages)

            return allowed, deferred, 0.0

    def commit_reservations(self, tasks):
        task_ids = [t.id for t in tasks]
        with self.lock:
            files = 0
            high_pages = 0
            for task_id in task_ids:
                reservation = self.pending.pop(task_id, None)
                if reservation:
                    files += reservation[0]
                    high_pages += reservation[1]

            if not files:
                return

            conn = get_conn()
            quota_date = self._quota_date()
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO api_quota_usage
                (quota_date, daily_files, high_priority_pages, updated_at)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT(quota_date) DO UPDATE SET
                    daily_files = daily_files + excluded.daily_files,
                    high_priority_pages = high_priority_pages + excluded.high_priority_pages,
                    updated_at = excluded.updated_at
                """,
                (quota_date, files, high_pages, time.time()),
            )
            conn.commit()

            logger.info(
                f"[QUOTA] commit files={files} high_pages={high_pages} "
                f"date={quota_date}"
            )

    def release_reservations(self, tasks):
        with self.lock:
            released = 0
            for task in tasks:
                if self.pending.pop(task.id, None):
                    released += 1

            if released:
                logger.info(f"[QUOTA] release files={released}")

    def snapshot(self):
        with self.lock:
            self._refill()
            used_files, used_high_pages = self._usage()
            pending_files, pending_high_pages = self._pending_totals()
            return {
                "daily_files": used_files,
                "daily_remaining": max(
                    0,
                    self.daily_file_limit - used_files - pending_files,
                ),
                "high_priority_pages": used_high_pages,
                "high_priority_remaining": max(
                    0,
                    self.high_priority_page_limit - used_high_pages - pending_high_pages,
                ),
                "minute_tokens": int(math.floor(self.tokens)),
                "pending_files": pending_files,
            }
