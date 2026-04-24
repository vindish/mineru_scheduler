from concurrent.futures import ThreadPoolExecutor


from queue import Queue
import threading

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

        self.executor.submit(wrapper)