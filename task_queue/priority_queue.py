# task_queue/priority_queue.py

def sort_by_priority(tasks):
    """
    简单优先级：
    FAILED > POLLING > INIT > DONE
    """

    priority_map = {
        "FAILED": 0,
        "DOWNLOADING": 1,
        # "POLLING": 2,
        "PUT_DONE": 3,
        "UPLOADED": 4,
        "INIT": 5,
    }

    return sorted(tasks, key=lambda t: priority_map.get(t[2], 99))