import threading
import time
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor, execute_values

from config.settings import DATABASE_URL, PG_CONN_KWARGS, VALID_TRANSITIONS
from db.task_row import TaskRow
from utils.logger import logger


db_lock = threading.Lock()
_local = threading.local()


def get_conn():
    if not hasattr(_local, "conn") or _local.conn.closed:
        if DATABASE_URL:
            conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
        else:
            conn = psycopg2.connect(cursor_factory=RealDictCursor, **PG_CONN_KWARGS)
        # Autocommit mode: every statement is its own transaction. This avoids
        # "InFailedSqlTransaction" cascading errors when one statement fails
        # mid-batch on a long-lived thread-local connection.
        conn.autocommit = True
        _local.conn = conn
    return _local.conn


def get_cursor():
    return get_conn().cursor()


def close_thread_conn():
    conn = getattr(_local, "conn", None)
    if conn and not conn.closed:
        conn.close()
    if hasattr(_local, "conn"):
        delattr(_local, "conn")


def init_db():
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            id BIGSERIAL PRIMARY KEY,
            file_path TEXT,
            file_name TEXT,
            status TEXT,
            api_task_id TEXT,
            upload_url TEXT,
            zip_url TEXT,
            retry_count INTEGER DEFAULT 0,
            max_retry INTEGER DEFAULT 5,
            next_run_time DOUBLE PRECISION,
            locked INTEGER DEFAULT 0,
            locked_at BIGINT,
            last_error TEXT,
            error_type TEXT,
            parent_id BIGINT,
            dead_at DOUBLE PRECISION,
            page_count INTEGER,
            created_at DOUBLE PRECISION,
            updated_at DOUBLE PRECISION
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_status ON tasks(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_locked ON tasks(locked)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_next_run ON tasks(next_run_time)")
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_file_path ON tasks(file_path)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_parent_id ON tasks(parent_id)")
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS api_quota_usage (
            quota_date TEXT PRIMARY KEY,
            daily_files INTEGER DEFAULT 0,
            high_priority_pages INTEGER DEFAULT 0,
            updated_at DOUBLE PRECISION
        )
        """
    )
    conn.commit()


def fetch_pending_tasks(conn):
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tasks WHERE status='PENDING'")
    return [TaskRow(r) for r in cursor.fetchall()]


def ensure_schema():
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'tasks'
        AND table_schema = 'public'
        """
    )
    columns = {row["column_name"] for row in cursor.fetchall()}

    migrations = {
        "parent_id": "ALTER TABLE tasks ADD COLUMN parent_id BIGINT",
        "dead_at": "ALTER TABLE tasks ADD COLUMN dead_at DOUBLE PRECISION",
        "error_type": "ALTER TABLE tasks ADD COLUMN error_type TEXT",
        "locked_at": "ALTER TABLE tasks ADD COLUMN locked_at BIGINT",
        "updated_at": "ALTER TABLE tasks ADD COLUMN updated_at DOUBLE PRECISION",
        "page_count": "ALTER TABLE tasks ADD COLUMN page_count INTEGER",
    }

    with db_lock:
        for name, sql in migrations.items():
            if name not in columns:
                cursor.execute(sql)
                logger.info(f"[DB MIGRATION] added column: {name}")

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_status ON tasks(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_locked ON tasks(locked)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_next_run ON tasks(next_run_time)")
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_file_path ON tasks(file_path)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_parent_id ON tasks(parent_id)")
        conn.commit()


def fetch_runnable_tasks(limit=200):
    conn = get_conn()
    cursor = conn.cursor()
    now = time.time()

    cursor.execute(
        """
        SELECT *
        FROM tasks
        WHERE locked = 0
        AND status NOT IN ('DEAD', 'DOWNLOADED', 'SPLIT_DONE')
        AND (next_run_time IS NULL OR next_run_time <= %s)
        ORDER BY id
        LIMIT %s
        """,
        (now, limit),
    )
    return [TaskRow(r) for r in cursor.fetchall()]


def heal_locks(timeout=300):
    conn = get_conn()
    cursor = conn.cursor()
    now = int(time.time())

    cursor.execute(
        """
        UPDATE tasks
        SET locked = 0, locked_at = NULL, updated_at = %s
        WHERE locked = 1
        AND locked_at IS NOT NULL
        AND (%s - locked_at > %s)
        """,
        (time.time(), now, timeout),
    )
    unlock_timeout = cursor.rowcount

    cursor.execute(
        """
        UPDATE tasks
        SET locked = 0, locked_at = NULL, updated_at = %s
        WHERE locked = 1
        AND locked_at IS NULL
        """,
        (time.time(),),
    )
    unlock_broken = cursor.rowcount

    conn.commit()
    return unlock_timeout, unlock_broken


def lock_tasks(task_ids):
    if not task_ids:
        return []

    conn = get_conn()
    cursor = conn.cursor()
    now = int(time.time())

    with db_lock:
        cursor.execute(
            """
            UPDATE tasks
            SET locked = 1, locked_at = %s
            WHERE id = ANY(%s)
            AND locked = 0
            RETURNING id
            """,
            (now, list(task_ids)),
        )
        rows = cursor.fetchall()
        conn.commit()
        return [r["id"] for r in rows]


def unlock_tasks(task_ids):
    if not task_ids:
        return

    conn = get_conn()
    cursor = conn.cursor()
    with db_lock:
        cursor.execute(
            """
            UPDATE tasks
            SET locked = 0, locked_at = NULL, updated_at = %s
            WHERE id = ANY(%s)
            """,
            (time.time(), list(task_ids)),
        )
        conn.commit()


def update_tasks(updates):
    if not updates:
        return

    for u in updates:
        if not isinstance(u, TaskRow):
            raise TypeError(f"update_tasks only accepts TaskRow, got {type(u)}")

    conn = get_conn()
    cursor = conn.cursor()

    with db_lock:
        for u in updates:
            task_id = u.id
            if not task_id:
                continue

            cursor.execute("SELECT status FROM tasks WHERE id=%s", (task_id,))
            row = cursor.fetchone()
            if not row:
                continue

            old_status = row["status"]
            new_status = u.status
            allowed = VALID_TRANSITIONS.get(old_status, [])

            if new_status and new_status not in allowed:
                logger.error(f"[INVALID TRANSITION] {old_status} → {new_status}")
                continue

            fields = []
            values = []

            # Skip columns we always overwrite below to avoid duplicate
            # assignments. Handlers commonly set `locked = 0` redundantly;
            # `updated_at` is always stamped here; the row id is the WHERE key.
            reserved = {"id", "locked", "locked_at", "updated_at"}
            seen = set()
            for k, v in u.items():
                if k in reserved or k in seen:
                    continue
                seen.add(k)
                fields.append(f"{k} = %s")
                values.append(v)

            # always release the lock and stamp updated_at
            fields.append("locked = %s")
            values.append(0)
            fields.append("locked_at = %s")
            values.append(None)
            fields.append("updated_at = %s")
            values.append(time.time())
            values.append(task_id)

            sql = f"UPDATE tasks SET {', '.join(fields)} WHERE id = %s"
            cursor.execute(sql, values)

        conn.commit()


def insert_tasks(new_tasks):
    for t in new_tasks:
        if not isinstance(t, TaskRow):
            raise TypeError("insert_tasks only accepts TaskRow")
    if not new_tasks:
        return

    conn = get_conn()
    now = time.time()
    rows = [
        (
            t.file_path,
            Path(t.file_path).name,
            t.status,
            getattr(t, "parent_id", None),
            now,
        )
        for t in new_tasks
    ]

    with db_lock:
        with conn.cursor() as cursor:
            execute_values(
                cursor,
                """
                INSERT INTO tasks
                (file_path, file_name, status, parent_id, created_at)
                VALUES %s
                ON CONFLICT (file_path) DO NOTHING
                """,
                rows,
            )
        conn.commit()
