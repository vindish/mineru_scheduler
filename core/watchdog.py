import time
import threading
from db.repository import get_conn,heal_locks
from utils.logger import logger


class Watchdog:

    def __init__(self, interval=60):
        self.interval = interval
        self._started = False

    def start(self):
        if self._started:
            return
        self._started = True

        t = threading.Thread(target=self.run, daemon=True)
        t.start()

    def run(self):
        while True:
            logger.info("[WATCHDOG] running")
            try:


                conn = get_conn()
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT COUNT(*) AS count
                    FROM tasks
                    WHERE locked=1
                """)
                locked_total = cursor.fetchone()["count"]

                logger.info(f"[WATCHDOG] locked_total={locked_total}")
                
                unlock, broken = heal_locks(timeout=300)
                logger.info(f"[WATCHDOG] unlock={unlock} broken={broken}")

                logger.info("[WATCHDOG] running")

            except Exception:
                logger.exception("[WATCHDOG ERROR]")

            time.sleep(self.interval)
