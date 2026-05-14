CREATE TABLE IF NOT EXISTS tasks (
    id BIGSERIAL PRIMARY KEY,
    file_path TEXT,
    file_name TEXT,
    status TEXT,
    api_task_id TEXT,
    upload_url TEXT,
    zip_url TEXT,
    retry_count INTEGER DEFAULT 0,
    max_retry INTEGER DEFAULT 5,
    next_run_time DOUBLE PRECISION,
    locked INTEGER DEFAULT 0,
    locked_at BIGINT,
    last_error TEXT,
    error_type TEXT,
    parent_id BIGINT,
    dead_at DOUBLE PRECISION,
    page_count INTEGER,
    created_at DOUBLE PRECISION,
    updated_at DOUBLE PRECISION
);

CREATE INDEX IF NOT EXISTS idx_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_locked ON tasks(locked);
CREATE INDEX IF NOT EXISTS idx_next_run ON tasks(next_run_time);
CREATE UNIQUE INDEX IF NOT EXISTS idx_file_path ON tasks(file_path);
CREATE INDEX IF NOT EXISTS idx_parent_id ON tasks(parent_id);

CREATE TABLE IF NOT EXISTS api_quota_usage (
    quota_date TEXT PRIMARY KEY,
    daily_files INTEGER DEFAULT 0,
    high_priority_pages INTEGER DEFAULT 0,
    updated_at DOUBLE PRECISION
);
