import time
from pathlib import Path

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from db.repository import get_conn
from utils.logger import logger


class PDFHandler(FileSystemEventHandler):

    def __init__(self):
        self.conn = get_conn()
        self.cursor = self.conn.cursor()

    def on_created(self, event):
        if event.is_directory:
            return

        path = Path(event.src_path)

        if path.suffix.lower() != ".pdf":
            return

        try:
            p = str(path.resolve())

            self.cursor.execute("""
                INSERT OR IGNORE INTO tasks
                (file_path, file_name, status, created_at)
                VALUES (?, ?, 'INIT', ?)
            """, (p, path.name, time.time()))

            self.conn.commit()

            logger.info(f"[WATCH] 新文件: {p}")

        except Exception as e:
            logger.error(f"[WATCH ERROR] {e}")


def start_watcher(scan_dirs):
    observer = Observer()

    handler = PDFHandler()

    for d in scan_dirs:
        p = Path(d)
        if not p.exists():
            logger.info(f"[WATCH] 目录不存在: {p}")
            continue

        observer.schedule(handler, str(p), recursive=True)

    observer.start()

    logger.info("[WATCH] 文件监听已启动")

    return observer