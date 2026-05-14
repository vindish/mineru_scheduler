import time
from threading import Lock

from utils.logger import logger


class RateLimiter:
    """
    单进程级别的限速器，三件事：
      1) 平稳控速（按 QPS 间隔节流）
      2) 全局冷却（cool_down(seconds)；429 / Retry-After 时所有 acquire 都阻塞）
      3) 自适应（根据 success/fail 比例动态调 QPS）
    """

    def __init__(self, base_qps=5):
        self.qps = float(base_qps)
        self.interval = 1.0 / self.qps

        self.lock = Lock()

        # 节流状态
        self.last = 0.0
        # 全局冷却到何时
        self.cooldown_until = 0.0

        # 统计
        self.success = 0
        self.fail = 0
        self.last_adjust = time.time()

    # ------------------------------------------------------------------
    # 速率控制
    # ------------------------------------------------------------------
    def _set_qps(self, new_qps):
        """改 qps 必须同时改 interval，否则节流不会变。"""
        self.qps = max(0.1, float(new_qps))
        self.interval = 1.0 / self.qps

    def acquire(self):
        """阻塞直到“可以发出下一次请求”。冷却期内全部阻塞等待。"""
        while True:
            with self.lock:
                now = time.time()
                wait_cd = self.cooldown_until - now
                if wait_cd > 0:
                    wait = wait_cd
                else:
                    delta = now - self.last
                    wait = max(0.0, self.interval - delta) if self.last else 0.0
                    if wait <= 0:
                        self.last = now
                        return
            # 锁外 sleep，避免阻塞其他线程
            time.sleep(wait)

    def cool_down(self, seconds):
        """触发全局冷却；多次调用会取较远的那个时间点。"""
        if seconds <= 0:
            return
        with self.lock:
            target = time.time() + float(seconds)
            if target > self.cooldown_until:
                self.cooldown_until = target
        logger.warning(f"[QPS] cooldown engaged: {seconds:.1f}s")

    # ------------------------------------------------------------------
    # 统计
    # ------------------------------------------------------------------
    def record_success(self):
        with self.lock:
            self.success += 1

    def record_fail(self):
        with self.lock:
            self.fail += 1

    def adjust(self):
        """每 2 秒最多调一次 QPS。少量样本时不动。"""
        with self.lock:
            now = time.time()
            if now - self.last_adjust < 2:
                return
            total = self.success + self.fail
            if total < 10:
                return

            fail_rate = self.fail / total
            if fail_rate > 0.3:
                self._set_qps(self.qps * 0.7)
            elif fail_rate < 0.1:
                self._set_qps(min(50.0, self.qps * 1.2))

            qps = self.qps
            interval = self.interval
            success = self.success
            fail = self.fail

            self.success = 0
            self.fail = 0
            self.last_adjust = now

        logger.info(
            f"[QPS] qps={qps:.2f} interval={interval:.3f}s "
            f"success={success} fail={fail} fail_rate={fail_rate:.2f}"
        )
