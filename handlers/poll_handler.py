import time
from db.repository import update_tasks
from utils.logger import logger
from services.mineru_client import MineruClient, RateLimitError
from db.task_row import TaskRow

API = "https://mineru.net/api/v4/extract-results/batch/"


class PollHandler:
    def __init__(self, rate_limiter=None):
        self.rate_limiter = rate_limiter
        self.client = MineruClient(rate_limiter=self.rate_limiter)

    def _find_result(self, extract_list, task):
        if not extract_list:
            return None

        task_data_id = str(task.id)
        task_file_name = str(task.file_name)

        for item in extract_list:
            if str(item.get("data_id")) == task_data_id:
                return item

        for item in extract_list:
            if str(item.get("file_name")) == task_file_name:
                return item

        return None

    def handle_batch(self, tasks: list[TaskRow]):
        updates = []
        logger.info(f"[POLL] batch={len(tasks)}")

        # 避免同一个 batch_id 重复轮询，按 api_task_id 分组
        groups = {}
        for t in tasks:
            batch_id = t.api_task_id
            groups.setdefault(batch_id, []).append(t)

        now = time.time()

        for batch_id, group in groups.items():
            if not batch_id:
                for t in group:
                    t.status = "FAILED"
                    t.last_error = "missing api_task_id"
                    updates.append(t)
                continue

            done = 0
            polling = 0
            failed = 0
            logger.info(f"[POLL] batch_id={batch_id} tasks={len(group)}")

            try:
                resp = self.client.poll_batch(batch_id)
                extract_list = resp.get("data", {}).get("extract_result", [])

                for t in group:
                    item = self._find_result(extract_list, t)

                    if item is None:
                        t.status = "PUT_DONE"
                        t.last_error = None
                        updates.append(t)
                        polling += 1
                        continue

                    state = item.get("state")
                    if state == "done":
                        t.status = "DOWNLOADING"
                        t.zip_url = item.get("full_zip_url")
                        t.last_error = None
                        updates.append(t)
                        done += 1
                    elif state == "failed":
                        t.status = "FAILED"
                        t.last_error = item.get("err_msg")
                        updates.append(t)
                        failed += 1
                    else:
                        t.status = "PUT_DONE"
                        t.last_error = None
                        updates.append(t)
                        polling += 1

            except RateLimitError as e:
                wait = max(1.0, float(getattr(e, "retry_after", 0) or 0))
                logger.warning(f"[POLL 429] batch_id={batch_id} cool_down={wait:.1f}s")
                for t in group:
                    t.status = "PUT_DONE"
                    t.next_run_time = now + wait
                    t.last_error = f"429 throttled: wait={wait:.1f}s"
                    updates.append(t)

            except Exception as e:
                err = str(e)
                logger.warning(f"[POLL ERROR] batch_id={batch_id} error={err}")
                for t in group:
                    t.status = "PUT_DONE"
                    t.next_run_time = now + 30
                    t.last_error = err
                    updates.append(t)

            logger.info(f"[POLL] batch_id={batch_id} done={done} polling={polling} failed={failed}")

        if updates:
            update_tasks(updates)
