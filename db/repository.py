import sqlite3
import time
from pathlib import Path
import threading
from services.storage import Storage
from db.task_row import TaskRow
from config.settings import VALID_TRANSITIONS
from utils.logger import logger

db_lock = threading.Lock()

storage = Storage()

db_path = storage.get_db_path()

# ✅ 线程局部存储
_local = threading.local()



def fetch_pending_tasks(conn):
    rows = conn.execute("SELECT * FROM tasks WHERE status='PENDING'").fetchall()
    return [TaskRow(r) for r in rows]


def get_conn():
    if not hasattr(_local, "conn"):
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA temp_store=MEMORY;")
        conn.execute("PRAGMA cache_size=-10000;")  # 10MB cache
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        _local.conn = conn
    return _local.conn


def get_cursor():
    return get_conn().cursor()


def fetch_runnable_tasks(limit=200):
    conn = get_conn()
    cursor = conn.cursor()

    now = time.time()

    rows = cursor.execute("""
        SELECT * FROM tasks
        WHERE (locked=0 OR (? - locked_at > 300))
        AND status NOT IN ('DEAD', 'DOWNLOADED', 'SPLIT_DONE')
        AND (next_run_time IS NULL OR next_run_time <= ?)
        LIMIT ?
    """, (now,now, limit)).fetchall()

    return [TaskRow(r) for r in rows]   # 🔥 核心改动


def heal_locks(timeout=300):
    conn = get_conn()
    cursor = conn.cursor()

    now = int(time.time())

    # 1️⃣ 超时锁
    cursor.execute("""
        UPDATE tasks
        SET locked=0, locked_at=NULL
        WHERE locked=1 
        AND locked_at IS NOT NULL
        AND (? - locked_at > ?)
    """, (now, timeout))
    unlock_timeout = cursor.rowcount

    # 2️⃣ 异常锁（没有时间）
    cursor.execute("""
        UPDATE tasks
        SET locked=0, locked_at=NULL
        WHERE locked=1 
        AND locked_at IS NULL
    """)
    unlock_broken = cursor.rowcount

    conn.commit()

    return unlock_timeout, unlock_broken

def lock_tasks(task_ids):
    conn = get_conn()
    cursor = conn.cursor()

    now = int(time.time())
    success = []

    with db_lock:   # ✅ 防并发抢锁冲突 改成✅ 更优写法（批量锁）
        cursor.execute(f"""
                UPDATE tasks
                SET locked=1, locked_at=?
                WHERE id IN ({','.join(['?']*len(task_ids))})
                AND locked=0
            """, [now, *task_ids])

        for tid in task_ids:

            if cursor.rowcount == 1:
                success.append(tid)

        conn.commit()

    return success


def update_tasks(updates):
    if not updates:
        return

    for u in updates:
        if not isinstance(u, TaskRow):
            raise TypeError(f"update_tasks only accepts TaskRow, got {type(u)}")

    conn = get_conn()
    cursor = conn.cursor()

    with db_lock:   # ✅ 加锁
        for u in updates:
            row = None   # 🔥 必须加
            if isinstance(u, TaskRow):
                task_id = u.id
            else:
                task_id = u.get("task_id")
            if not task_id:
                continue
            cur = cursor.execute("SELECT status FROM tasks WHERE id=?", (task_id,))
            row = cur.fetchone()
            if not row:
                continue

            # old_status = row[0]
            old_status = row["status"]
            if isinstance(u, TaskRow):
                new_status = u.status
            else:
                new_status = u.get("status")

            allowed = VALID_TRANSITIONS.get(old_status, [])

            if new_status and new_status not in allowed:
                logger.error(f"[INVALID TRANSITION] {old_status} → {new_status}")
                continue

            fields = []
            values = []

            for k, v in u.items():
                if k == task_id:
                    continue
                fields.append(f"{k}=?")
                values.append(v)

            fields.append("locked=0")
            fields.append("updated_at=?")
            values.append(time.time())
            values.append(task_id)

            sql = f"UPDATE tasks SET {','.join(fields)} WHERE id=?"
            cursor.execute(sql, values)

        conn.commit()   # ✅ 一次提交



def insert_tasks(new_tasks):
    for t in new_tasks:
        if not isinstance(t, TaskRow):
            raise TypeError("insert_tasks only accepts TaskRow")
    if not new_tasks:
        return

    conn = get_conn()
    cursor = conn.cursor()

    now = time.time()

    with db_lock:   # ✅ 加锁
        
        cursor.executemany("""
        INSERT OR IGNORE INTO tasks 
        (file_path, file_name, status, parent_id, created_at)
        VALUES (?, ?, ?, ?, ?)
        """, [
            (
                t.file_path,
                Path(t.file_path).name,
                t.status,
                getattr(t, "parent_id", None),  # 🔥 核心
                now
            )
            for t in new_tasks
        ])

        conn.commit()


