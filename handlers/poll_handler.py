import json
import time
from db.repository import update_tasks
from config.settings import TOKEN
from utils.logger import logger
from services.mineru_client import MineruClient
# from services.storage import Storage
from db.task_row import TaskRow

API = "https://mineru.net/api/v4/extract-results/batch/"


class PollHandler:
    def __init__(self, rate_limiter=None):
        self.rate_limiter = rate_limiter
        self.client = MineruClient(rate_limiter=self.rate_limiter)
    
    def handle_batch(self, tasks: list[TaskRow]):
        updates = []
        logger.info(f"[POLL] batch={len(tasks)}")
        logger.info(f"[POLL] batch={len(tasks)}")
        for t in tasks:


            tid = t.id
            batch_id = t.api_task_id
            file_name = t.file_name
            old_status = t.status

            done = 0
            polling = 0
            failed = 0
            url = API + f"{batch_id}"
            # logger.info(f"[POLL URL] URL={url}")


            try:
                resp = self.client.poll_batch(batch_id)
                if resp.get("code") != 0:
                    raise RuntimeError(resp.get("msg"))

                # 🔥 完整JSON
                # new_json_str = json.dumps(resp, ensure_ascii=False)
                extract_list = resp.get("data", {}).get("extract_result", [])

                # 🔥 构建映射（关键）
                result_map = {}
                for r in extract_list:
                    fname = r.get("file_name")
                    if fname:
                        result_map[fname] = r


                found = False

                for item in extract_list:
                    # result = result_map.get(file_name)

                    # if result:
                    #     state = result["state"]

                    if str(item["file_name"]) != file_name:
                        continue

                    found = True

                    if item["state"] == "done":
                        t.status = "DOWNLOADING"
                        t.zip_url = item.get("full_zip_url")
                        updates.append(t)

                        done += 1
                    elif item["state"] == "failed":
                        errmsg = item["err_msg"]

                        t.status = "FAILED"
                        t.last_error = errmsg
                        updates.append(t)

                        failed += 1
                    else:
                        t.status = "PUT_DONE"
                        updates.append(t)
                        polling += 1

                if not found:
                    t.status = "PUT_DONE"
                    updates.append(t)

            except Exception as e:
                
                t.status = "FAILED"
                t.last_error = str(e)
                updates.append(t)
            logger.info(f"[POLL] done={done} polling={polling} failed={failed}")
        if updates:
            update_tasks(updates)

        