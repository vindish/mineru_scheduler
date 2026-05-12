from concurrent.futures import ThreadPoolExecutor
import threading
from utils.logger import logger

class WorkerPool:
    def __init__(self, max_workers):
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.semaphore = threading.Semaphore(max_workers * 2)

    def submit(self, fn, *args):
        self.semaphore.acquire()

        def wrapper():
            try:
                fn(*args)
            finally:
                self.semaphore.release()

        future = self.executor.submit(wrapper)
        future.add_done_callback(self._log_failure)
        return future

    @staticmethod
    def _log_failure(future):
        exc = future.exception()
        if exc:
            logger.error(
                "[WORKER ERROR]",
                exc_info=(type(exc), exc, exc.__traceback__)
            )
