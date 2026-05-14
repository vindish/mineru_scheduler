import time
from pathlib import Path

from config.settings import SCAN_INTERVAL, SCAN_MAX_FILES, SCAN_BATCH_SLEEP
from utils.logger import logger
from db.repository import get_conn
from services.storage import Storage


def _iter_pdfs(base: Path):
    """大小写不敏感地遍历 *.pdf / *.PDF / *.Pdf 等。"""
    for path in base.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() != ".pdf":
            continue
        yield path


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
            logger.warning(
                f"[SCAN] 目录不存在，已跳过（不会自动创建以防屏蔽 NAS 挂载）: {base}"
            )
            continue

        if not base.is_dir():
            logger.warning(f"[SCAN] 不是目录，已跳过: {base}")
            continue

        try:
            iterator = _iter_pdfs(base)
        except PermissionError as e:
            logger.error(f"[SCAN] 无权限读取 {base}: {e}")
            continue

        for path in iterator:
            try:
                p = str(path.resolve())
            except OSError as e:
                logger.warning(f"[SCAN] resolve 失败已跳过: {path} ({e})")
                continue

            scanned += 1

            new_files.append((p, path.name))

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

    inserted = 0
    for p, name in new_files:
        cursor.execute("""
            INSERT INTO tasks
            (file_path, file_name, status, created_at)
            VALUES (%s, %s, 'INIT', %s)
            ON CONFLICT (file_path) DO NOTHING
            RETURNING id
        """, (p, name, now))
        if cursor.fetchone():
            inserted += 1

    conn.commit()

    logger.info(f"[SCAN] scanned={scanned} inserted={inserted}")
