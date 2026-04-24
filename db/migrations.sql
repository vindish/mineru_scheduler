INIT_SQL = """
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT,
    file_name TEXT,
    status TEXT,
    api_task_id TEXT,
    upload_url TEXT,
    zip_url TEXT,
    retry_count INTEGER DEFAULT 0,
    max_retry INTEGER DEFAULT 5,
    next_run_time REAL,
    locked INTEGER DEFAULT 0,
    locked_at INTEGER,
    last_error TEXT,
    error_type TEXT,
    dead_at REAL,
    created_at REAL,
    updated_at REAL
);

CREATE INDEX IF NOT EXISTS idx_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_locked ON tasks(locked);
CREATE INDEX IF NOT EXISTS idx_next_run ON tasks(next_run_time);
CREATE INDEX IF NOT EXISTS idx_file_path ON tasks(file_path);
"""