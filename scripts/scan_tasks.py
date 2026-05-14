import os
import time
from pathlib import Path

from psycopg2.extras import execute_values

from config.settings import SCAN_INTERVAL, SCAN_MAX_FILES, SCAN_BATCH_SLEEP
from utils.logger import logger
from db.repository import get_conn
from services.storage import Storage


# 每批向数据库 flush 的条数。在大 NAS 上必须分批 flush，
# 否则一次性遍历完所有文件再写库，调度器要等很久才能拿到任务。
SCAN_FLUSH_BATCH = 500


def _walk_pdfs(base: Path):
    """
    递归遍历 base 目录下的 PDF（大小写不敏感），用 os.scandir 替代
    Path.rglob：scandir 只读 dirent，不再为每个 entry 多 stat 一次，
    在含有几十万文件的网络盘上能快一个数量级，遇到坏 entry 也能继续。
    """
    stack = [str(base)]
    while stack:
        cur = stack.pop()
        try:
            it = os.scandir(cur)
        except (PermissionError, OSError) as e:
            logger.warning(f"[SCAN] 无法读取 {cur}: {e}")
            continue

        with it:
            for entry in it:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(entry.path)
                        continue
                    if not entry.is_file(follow_symlinks=False):
                        continue
                except OSError as e:
                    logger.warning(f"[SCAN] entry stat 失败 {entry.path}: {e}")
                    continue

                name = entry.name
                if not name.lower().endswith(".pdf"):
                    continue

                yield entry.path, name


def _flush(conn, cursor, rows):
    """批量 INSERT，已存在的路径跳过。返回新插入条数。"""
    if not rows:
        return 0
    now = time.time()
    payload = [(p, n, "INIT", now) for (p, n) in rows]
    execute_values(
        cursor,
        """
        INSERT INTO tasks (file_path, file_name, status, created_at)
        VALUES %s
        ON CONFLICT (file_path) DO NOTHING
        RETURNING id
        """,
        payload,
    )
    inserted = len(cursor.fetchall())
    conn.commit()
    return inserted


def scan_and_insert():
    storage = Storage()
    scan_dirs = storage.get_scan_dirs()

    conn = get_conn()
    cursor = conn.cursor()

    scanned = 0
    inserted_total = 0
    batch = []

    for scan_dir in scan_dirs:
        base = Path(scan_dir)

        if not base.exists():
            logger.warning(
                f"[SCAN] 目录不存在，已跳过（不会自动创建以防屏蔽 NAS 挂载）: {base}"
            )
            continue

        if not base.is_dir():
            logger.warning(f"[SCAN] 不是目录，已跳过: {base}")
            continue

        logger.info(f"[SCAN] 开始扫描: {base}")

        for path, name in _walk_pdfs(base):
            batch.append((path, name))
            scanned += 1

            # 攒够一批就 flush，让调度器尽快拿到任务
            if len(batch) >= SCAN_FLUSH_BATCH:
                ins = _flush(conn, cursor, batch)
                inserted_total += ins
                logger.info(
                    f"[SCAN] progress scanned={scanned} "
                    f"inserted_total={inserted_total} (this batch={ins})"
                )
                batch.clear()
                # 节流，避免猛拍数据库
                time.sleep(SCAN_BATCH_SLEEP)

            # 单次扫描总量上限
            if scanned >= SCAN_MAX_FILES:
                logger.warning(
                    f"[SCAN] 已达单次扫描上限 {SCAN_MAX_FILES}，剩余文件将在下一轮扫描"
                )
                break

        if scanned >= SCAN_MAX_FILES:
            break

    # 最后一批
    if batch:
        ins = _flush(conn, cursor, batch)
        inserted_total += ins
        batch.clear()

    if scanned == 0:
        logger.info("[SCAN] 无文件（来源目录为空或全部跳过）")
    else:
        logger.info(f"[SCAN] done scanned={scanned} inserted_total={inserted_total}")
