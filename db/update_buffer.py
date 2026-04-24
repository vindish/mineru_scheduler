class UpdateBuffer:

    def __init__(self, flush_size=10):
        self.buffer = []
        self.flush_size = flush_size

    def add(self, item):
        self.buffer.append(item)

        if len(self.buffer) >= self.flush_size:
            self.flush()

    def flush(self):
        if not self.buffer:
            return

        from db.repository import update_tasks
        update_tasks(self.buffer)
        self.buffer.clear()