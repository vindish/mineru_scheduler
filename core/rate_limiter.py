import time
from threading import Lock
from utils.logger import logger


class RateLimiter:

    def __init__(self, base_qps=5):
        self.qps = base_qps
        self.interval = 1.0 / self.qps

        self.lock = Lock()

        # 统计
        self.success = 0
        self.fail = 0
        self.last_adjust = time.time()

    def acquire(self):
        with self.lock:
            now = time.time()

            if hasattr(self, "last"):
                delta = now - self.last
                if delta < self.interval:
                    time.sleep(self.interval - delta)

            self.last = time.time()
            
    def record_success(self):
        with self.lock:
            self.success += 1

    def record_fail(self):
        with self.lock:
            self.fail += 1

    def adjust(self):
        now = time.time()

        # 每2秒调整一次
        if now - self.last_adjust < 2:
            return

        total = self.success + self.fail
        if total < 10:
            return

        fail_rate = self.fail / total

        if fail_rate > 0.3:
            self.qps = max(1, self.qps * 0.7)
        elif fail_rate < 0.1:
            self.qps = min(50, self.qps * 1.2)

        self.interval = 1.0 / self.qps

        logger.info(f"[QPS] adjust → {self.qps:.2f} fail_rate={fail_rate:.2f}")
        logger.info(
            f"[QPS] qps={self.qps:.2f} "
            f"interval={self.interval:.3f}s "
            f"success={self.success} "
            f"fail={self.fail}"
        )
        self.success = 0
        self.fail = 0
        self.last_adjust = now