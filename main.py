import time
import threading

from core.scheduler import Scheduler
from scripts.scan_tasks import scan_and_insert, get_active_backlog
from config.settings import SCAN_INTERVAL, SCAN_BACKLOG_HIGH, SCAN_BACKLOG_LOW
from utils.startup_check import run_checks
from utils.logger import logger
from db.repository import ensure_schema, get_conn, init_db


def scan_loop():
    """
    扫描线程 + 水位回压：
      - backlog ≥ HIGH 时，暂停扫描
      - 一旦暂停，必须等 backlog 跌到 LOW 才恢复（迟滞，避免抖动）
    """
    paused = False

    while True:
        try:
            backlog = get_active_backlog()

            if not paused and backlog >= SCAN_BACKLOG_HIGH:
                logger.info(
                    f"[SCAN] backlog={backlog} ≥ HIGH={SCAN_BACKLOG_HIGH}，暂停扫描"
                )
                paused = True

            if paused:
                if backlog <= SCAN_BACKLOG_LOW:
                    logger.info(
                        f"[SCAN] backlog={backlog} ≤ LOW={SCAN_BACKLOG_LOW}，恢复扫描"
                    )
                    paused = False
                else:
                    logger.info(
                        f"[SCAN] still paused; backlog={backlog} "
                        f"(等待降到 LOW={SCAN_BACKLOG_LOW} 再恢复)"
                    )
            else:
                scan_and_insert(stop_when_backlog_above=SCAN_BACKLOG_HIGH)

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

            cursor.execute("SELECT COUNT(*) AS count FROM tasks")
            total = cursor.fetchone()["count"]
            cursor.execute("SELECT COUNT(*) AS count FROM tasks WHERE status='DOWNLOADED'")
            done = cursor.fetchone()["count"]
            cursor.execute("SELECT COUNT(*) AS count FROM tasks WHERE status='FAILED'")
            failed = cursor.fetchone()["count"]

            logger.info(f"[MONITOR] total={total} done={done} failed={failed}")

        except Exception:
            logger.exception("[MONITOR ERROR]")

        time.sleep(5)

if __name__ == "__main__":
    logger.info("=== 系统启动 ===")

    try:
        run_checks()

        logger.info("🚀 系统启动")

        init_db()
        ensure_schema()

        threading.Thread(target=scan_loop, daemon=True).start()
        threading.Thread(target=monitor_loop, daemon=True).start()

        scheduler = Scheduler()
        scheduler.run()

    except Exception:
        logger.exception("❌ 启动失败")

    input("按回车退出...")
