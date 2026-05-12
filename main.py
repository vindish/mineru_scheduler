import time
import threading

from core.scheduler import Scheduler
from core.rate_limiter import RateLimiter
from scripts.scan_tasks import scan_and_insert
from config.settings import SCAN_INTERVAL, INIT_SQL
from utils.startup_check import run_checks
from utils.logger import logger
from db.repository import ensure_schema, get_conn


def scan_loop():
    while True:
        try:
            scan_and_insert()
        except Exception:
            logger.exception("[SCAN ERROR]")

        time.sleep(SCAN_INTERVAL)

def monitor_loop():
    from db.repository import get_conn
    import time

    while True:
        try:
            conn = get_conn()
            cursor = conn.cursor()

            total = cursor.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
            done = cursor.execute("SELECT COUNT(*) FROM tasks WHERE status='DOWNLOADED'").fetchone()[0]
            failed = cursor.execute("SELECT COUNT(*) FROM tasks WHERE status='FAILED'").fetchone()[0]

            logger.info(f"[MONITOR] total={total} done={done} failed={failed}")

        except Exception:
            logger.exception("[MONITOR ERROR]")

        time.sleep(5)

if __name__ == "__main__":
    logger.info("=== 系统启动 ===")

    try:
        run_checks()

        logger.info("🚀 系统启动")

        conn = get_conn()
        cursor = conn.cursor()
        cursor.executescript(INIT_SQL)
        conn.commit()
        ensure_schema()

        threading.Thread(target=scan_loop, daemon=True).start()
        threading.Thread(target=monitor_loop, daemon=True).start()

        scheduler = Scheduler()
        scheduler.run()

    except Exception:
        logger.exception("❌ 启动失败")

    input("按回车退出...")
