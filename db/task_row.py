class TaskRow:
    __slots__ = ("_data",)

    def __init__(self, raw, columns=None):
        from config.settings import TASK_COLUMNS

        cols = columns or TASK_COLUMNS

        if isinstance(raw, dict):
            self._data = dict(raw)
        elif hasattr(raw, "keys"):
            self._data = dict(raw)
        else:
            self._data = dict(zip(cols, raw))



    # 🔥 读取属性
    def __getattr__(self, item):
        if item in self._data:
            return self._data[item]
        raise AttributeError(f"TaskRow has no attribute '{item}'")

    # 🔥 设置属性
    def __setattr__(self, key, value):
        if key == "_data":
            super().__setattr__(key, value)
        else:
            self._data[key] = value

    # 🔥 dict访问
    def __getitem__(self, item):
        return self._data[item]

    def get(self, key, default=None):
        return self._data.get(key, default)

    def items(self):
        return self._data.items()

    def to_dict(self):
        return dict(self._data)

    def set(self, **kwargs):
        self._data.update(kwargs)
        return self

    @property
    def id(self):
        if "id" not in self._data:
            raise ValueError("TaskRow missing 'id'")
        return self._data["id"]

    def __repr__(self):
        return f"<TaskRow id={self._data.get('id')} status={self._data.get('status')}>"

    def reset(self):
        self.status = "INIT"
        self.retry_count = 0
        self.locked = 0
        self.api_task_id = None
        self.upload_url = None
        self.zip_url = None
        self.last_error = None
        return self
