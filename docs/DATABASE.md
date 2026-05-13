# Database

The project uses SQLite with WAL mode. The database path is built by `services/storage.py`:

```text
BASE_DIR / "db" / DB_NAME
```

Current default database name:

```text
tasks1.db
```

## Connection Setup

Owner: `db/repository.py:get_conn()`

Each thread gets its own SQLite connection through `threading.local()`.

Pragmas:

```sql
PRAGMA temp_store=MEMORY;
PRAGMA cache_size=-10000;
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
```

Python-level writes are protected by `db_lock = threading.Lock()`.

## Table: tasks

Primary task table.

### Columns

| Column | Type | Meaning |
| --- | --- | --- |
| `id` | `INTEGER PRIMARY KEY AUTOINCREMENT` | Task id. |
| `file_path` | `TEXT` | Absolute PDF path; unique. |
| `file_name` | `TEXT` | Display/file match name. |
| `status` | `TEXT` | State machine status. |
| `api_task_id` | `TEXT` | MinerU batch id. |
| `upload_url` | `TEXT` | MinerU/OSS upload URL. |
| `zip_url` | `TEXT` | Result ZIP URL. |
| `retry_count` | `INTEGER DEFAULT 0` | Retry count. |
| `max_retry` | `INTEGER DEFAULT 5` | Per-task max retry field. |
| `next_run_time` | `REAL` | Unix timestamp before which scheduler should skip the task. |
| `locked` | `INTEGER DEFAULT 0` | Scheduler lock flag. |
| `locked_at` | `INTEGER` | Lock timestamp. |
| `last_error` | `TEXT` | Latest error message. |
| `error_type` | `TEXT` | Dead-letter or categorized error. |
| `parent_id` | `INTEGER` | Parent task id for split child PDFs. |
| `dead_at` | `REAL` | Unix timestamp when task entered `DEAD`. |
| `page_count` | `INTEGER` | Cached PDF page count. |
| `created_at` | `REAL` | Created timestamp. |
| `updated_at` | `REAL` | Last update timestamp. |

### Indexes

```sql
CREATE INDEX IF NOT EXISTS idx_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_locked ON tasks(locked);
CREATE INDEX IF NOT EXISTS idx_next_run ON tasks(next_run_time);
CREATE UNIQUE INDEX IF NOT EXISTS idx_file_path ON tasks(file_path);
CREATE INDEX IF NOT EXISTS idx_parent_id ON tasks(parent_id);
```

## Table: api_quota_usage

Created by `core/quota_manager.py`.

Tracks MinerU daily quota usage.

| Column | Type | Meaning |
| --- | --- | --- |
| `quota_date` | `TEXT PRIMARY KEY` | Local date in `YYYY-MM-DD`. |
| `daily_files` | `INTEGER DEFAULT 0` | Submitted files counted for the day. |
| `high_priority_pages` | `INTEGER DEFAULT 0` | Locally counted high-priority pages. |
| `updated_at` | `REAL` | Last update timestamp. |

Important:

- `daily_files` increments only after `UploadHandler` successfully creates an upload batch.
- Pending reservations live in memory and are not written until commit.
- Failed upload batch reservations are released and never committed.

## Schema Initialization And Migration

Initial schema is duplicated in:

- `config/settings.py:INIT_SQL`
- `db/migrations.sql`

Runtime migration is handled by:

```text
db.repository.ensure_schema()
```

When adding a new task column:

1. Add it to `INIT_SQL`.
2. Add it to `TASK_COLUMNS`.
3. Add an idempotent migration in `ensure_schema()`.
4. Add it to `db/migrations.sql`.
5. Update this document.

## TaskRow Column Order

`TaskRow` can build from raw tuples using `TASK_COLUMNS`, so column order must match the task table when raw non-row tuples are used.

Most current queries use `sqlite3.Row`, but still keep `TASK_COLUMNS` accurate.

## Locking Model

Runnable tasks are selected by:

```sql
SELECT * FROM tasks
WHERE locked = 0
AND status NOT IN ('DEAD', 'DOWNLOADED', 'SPLIT_DONE')
AND (next_run_time IS NULL OR next_run_time <= ?)
LIMIT ?
```

Lock acquisition:

```sql
UPDATE tasks
SET locked=1, locked_at=?
WHERE id IN (...)
AND locked=0
```

After the update, the repository queries back the locked ids for the same `locked_at`.

Unlock happens through either:

- `update_tasks()`: normal handler completion.
- `unlock_tasks()`: dispatch errors or locked-but-not-dispatched tasks.
- `heal_locks()`: watchdog timeout cleanup.

## State Validation

`update_tasks()` reads the current persisted status, compares requested new status against `VALID_TRANSITIONS`, and skips invalid transitions.

If logs contain:

```text
[INVALID TRANSITION] OLD -> NEW
```

then update `config/settings.py:VALID_TRANSITIONS` only if the transition is actually valid.

## Useful SQL

Counts by status:

```sql
SELECT status, COUNT(*) AS count
FROM tasks
GROUP BY status
ORDER BY count DESC;
```

Locked tasks:

```sql
SELECT id, status, locked_at, file_name
FROM tasks
WHERE locked=1
ORDER BY locked_at;
```

Recent failures:

```sql
SELECT id, status, retry_count, file_name, last_error
FROM tasks
WHERE status='FAILED'
ORDER BY updated_at DESC
LIMIT 50;
```

Quota usage:

```sql
SELECT *
FROM api_quota_usage
ORDER BY quota_date DESC
LIMIT 10;
```

Tasks waiting for future retry/quota:

```sql
SELECT id, status, datetime(next_run_time, 'unixepoch') AS next_run, file_name
FROM tasks
WHERE next_run_time IS NOT NULL
AND next_run_time > strftime('%s', 'now')
ORDER BY next_run_time
LIMIT 50;
```

Split parent/child relation:

```sql
SELECT p.id AS parent_id, p.file_name AS parent_file, c.id AS child_id, c.file_name AS child_file, c.status
FROM tasks p
JOIN tasks c ON c.parent_id = p.id
WHERE p.id = ?;
```
