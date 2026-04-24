from handlers.upload_handler import UploadHandler
from handlers.put_handler import PutHandler
from handlers.poll_handler import PollHandler
from handlers.download_handler import DownloadHandler
from handlers.split_handler import SplitHandler
from handlers.fail_handler import FailHandler
from utils.logger import logger

class Dispatcher:

    def __init__(self, rate_limiter, upload_limiter, put_limiter, poll_limiter, download_limiter):
        self.rate_limiter = rate_limiter

        self.handlers = {
            "INIT": UploadHandler(upload_limiter),
            "UPLOADED": PutHandler(put_limiter),
            "PUT_DONE": PollHandler(poll_limiter),
            "DOWNLOADING": DownloadHandler(download_limiter),
            "SPLIT_NEEDED": SplitHandler(rate_limiter),
            "FAILED": FailHandler(rate_limiter),
        }
    def dispatch(self, status, tasks):

        handler = self.handlers.get(status)
        if not handler:
            return

        # 🔥 核心：二次过滤（必须）
        tasks = [t for t in tasks if t.status == status]

        if not tasks:
            return

        try:
            handler.handle_batch(tasks)
            logger.info(f"[DISPATCH] {status} -> {len(tasks)}")

        except Exception as e:
            logger.exception("[DISPATCH ERROR]")
