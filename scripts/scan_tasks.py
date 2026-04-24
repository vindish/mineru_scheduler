import time
from pathlib import Path

from config.settings import SCAN_INTERVAL, SCAN_MAX_FILES, SCAN_BATCH_SLEEP
from utils.logger import logger
from db.repository import get_conn
from services.storage import Storage

def scan_and_insert():
    storage = Storage()
    scan_dirs = storage.get_scan_dirs()

    conn = get_conn()
    cursor = conn.cursor()

    new_files = []
    scanned = 0

    for scan_dir in scan_dirs:
        base = Path(scan_dir)

        if not base.exists():
            logger.info(f"[SCAN] 目录不存在: {base}")
            continue

        for path in base.rglob("*.pdf"):
            p = str(path.resolve())   # 🔥 统一绝对路径

            scanned += 1

            new_files.append((p, Path(p).name))

            # 🔥 扫描上限（正确 break）
            if scanned >= SCAN_MAX_FILES:
                break

            # 🔥 节流
            if scanned % 200 == 0:
                time.sleep(SCAN_BATCH_SLEEP)

        # 🔥 外层也要 break
        if scanned >= SCAN_MAX_FILES:
            break

    if not new_files:
        logger.info(f"[SCAN] 无新增文件（扫描:{scanned}）")
        return

    now = time.time()

    # 🔥 直接交给数据库去重
    cursor.executemany("""
        INSERT OR IGNORE INTO tasks 
        (file_path, file_name, status, created_at)
        VALUES (?, ?, 'INIT', ?)
    """, [
        (p, name, now)
        for p, name in new_files
    ])

    conn.commit()

    inserted = cursor.rowcount  # ⚠️ SQLite 不完全准确，但可参考

    logger.info(f"[SCAN] scanned={scanned} inserted≈{inserted}")


