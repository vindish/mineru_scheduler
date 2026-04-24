import time
from db.repository import update_tasks
from config.settings import MAX_RETRY, RETRY_DELAY
from utils.logger import logger
from db.task_row import TaskRow
from utils.backoff import exponential_backoff


class RetryHandler:

    def __init__(self, max_retry=MAX_RETRY, backoff_base=2):
        self.max_retry = max_retry


    def handle_batch(self, tasks: list[TaskRow]):
        updates = []
        logger.info(f"[retry] batch={len(tasks)}")
        logger.info(f"[retry] batch={len(tasks)}")
        for t in tasks:
            task_id = t.id 
            retry_count =  t.retry_count

            if retry_count >= self.max_retry:
                t.status = "DEAD"
                updates.append(t)

                continue

            delay = exponential_backoff(retry_count)
            # delay = RETRY_DELAY * (retry_count + 1)
            

            t.status = "INIT"
            t.retry_count = retry_count + 1
            t.next_run_time = time.time() + delay
            updates.append(t)
        if updates:
            update_tasks(updates)