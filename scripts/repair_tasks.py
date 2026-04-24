from db.repository import update_tasks
from db.task_row import TaskRow
import sys

def repair_dead(task_ids):
    updates = []

    for tid in task_ids:
        task = TaskRow({"id": tid}).reset()
        updates.append(task)

    update_tasks(updates)

    logger.info(f"[REPAIR] reset tasks: {task_ids}")




if __name__ == "__main__":
    if len(sys.argv) > 1:
        ids = list(map(int, sys.argv[1:]))
        repair_dead(ids)
    else:
        repair_dead([1, 2, 3])