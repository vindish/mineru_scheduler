from db.repository import update_tasks
import time


class DeadLetterQueue:

    def push_batch(self, tasks, error_type="UNKNOWN"):
        updates = []

        for t in tasks:
            t.status = "DEAD"
            t.error_type = error_type
            t.dead_at = time.time()
            updates.append(t)
        update_tasks(updates)