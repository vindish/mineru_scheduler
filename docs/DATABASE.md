# Database

The project uses PostgreSQL through `psycopg2`. SQLite has been removed because the previous DB file lived on NAS and caused reliability issues.

## Connection

Owner: `db/repository.py:get_conn()`

Connection priority:

1. `DATABASE_URL`, if set.
2. `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`.

Cursor type:

```text
psycopg2.extras.RealDictCursor
```

Each Python thread uses a thread-local connection.

## Schema Init

Runtime initialization:

```text
main.py -> init_db() -> ensure_schema()
```

Reference SQL:

```text
db/migrations.sql
```

## Table: tasks

| Column | Type | Meaning |
| --- | --- | --- |
| `id` | `BIGSERIAL PRIMARY KEY` | Task id. |
| `file_path` | `TEXT` | Absolute PDF path; unique index. |
| `file_name` | `TEXT` | File name used for MinerU result matching. |
| `status` | `TEXT` | State machine status. |
| `api_task_id` | `TEXT` | MinerU batch id. |
| `upload_url` | `TEXT` | MinerU/OSS upload URL. |
| `zip_url` | `TEXT` | Result ZIP URL. |
| `retry_count` | `INTEGER DEFAULT 0` | Retry count. |
| `max_retry` | `INTEGER DEFAULT 5` | Per-task max retry field. |
| `next_run_time` | `DOUBLE PRECISION` | Unix timestamp for delayed scheduling. |
| `locked` | `INTEGER DEFAULT 0` | Scheduler lock flag. |
| `locked_at` | `BIGINT` | Lock timestamp. |
| `last_error` | `TEXT` | Latest error. |
| `error_type` | `TEXT` | Error category, especially for dead letter. |
| `parent_id` | `BIGINT` | Parent task id for split children. |
| `dead_at` | `DOUBLE PRECISION` | Unix timestamp when moved to `DEAD`. |
| `page_count` | `INTEGER` | Cached PDF page count. |
| `created_at` | `DOUBLE PRECISION` | Created timestamp. |
| `updated_at` | `DOUBLE PRECISION` | Last update timestamp. |

Indexes:

```sql
CREATE INDEX IF NOT EXISTS idx_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_locked ON tasks(locked);
CREATE INDEX IF NOT EXISTS idx_next_run ON tasks(next_run_time);
CREATE UNIQUE INDEX IF NOT EXISTS idx_file_path ON tasks(file_path);
CREATE INDEX IF NOT EXISTS idx_parent_id ON tasks(parent_id);
```

## Table: api_quota_usage

| Column | Type | Meaning |
| --- | --- | --- |
| `quota_date` | `TEXT PRIMARY KEY` | Local date `YYYY-MM-DD`. |
| `daily_files` | `INTEGER DEFAULT 0` | Committed submitted file count. |
| `high_priority_pages` | `INTEGER DEFAULT 0` | Local high-priority page count. |
| `updated_at` | `DOUBLE PRECISION` | Last update timestamp. |

Quota is committed only after MinerU upload batch creation succeeds.

## PostgreSQL Query Conventions

Use:

```sql
WHERE id = %s
WHERE id = ANY(%s)
ON CONFLICT (file_path) DO NOTHING
RETURNING id
```

Do not use:

```sql
?
INSERT OR IGNORE
AUTOINCREMENT
```

## Locking

Fetch:

```sql
SELECT *
FROM tasks
WHERE locked = 0
AND status NOT IN ('DEAD', 'DOWNLOADED', 'SPLIT_DONE')
AND (next_run_time IS NULL OR next_run_time <= %s)
ORDER BY id
LIMIT %s;
```

Lock:

```sql
UPDATE tasks
SET locked = 1, locked_at = %s
WHERE id = ANY(%s)
AND locked = 0
RETURNING id;
```

Unlock:

```sql
UPDATE tasks
SET locked = 0, locked_at = NULL, updated_at = %s
WHERE id = ANY(%s);
```

## State Validation

`update_tasks()` reads the current persisted status, validates requested new status against `VALID_TRANSITIONS`, and skips invalid updates.

If logs contain:

```text
[INVALID TRANSITION] OLD → NEW
```

fix the handler or add the transition only if the lifecycle truly allows it.

## Useful psql Commands

Task counts:

```bash
docker compose exec postgres psql -U mineru -d mineru_scheduler \
  -c "SELECT status, COUNT(*) FROM tasks GROUP BY status ORDER BY COUNT(*) DESC;"
```

Quota:

```bash
docker compose exec postgres psql -U mineru -d mineru_scheduler \
  -c "SELECT * FROM api_quota_usage ORDER BY quota_date DESC LIMIT 5;"
```

Locked tasks:

```bash
docker compose exec postgres psql -U mineru -d mineru_scheduler \
  -c "SELECT id, status, locked_at, file_name FROM tasks WHERE locked=1 ORDER BY locked_at;"
```

Recent failures:

```bash
docker compose exec postgres psql -U mineru -d mineru_scheduler \
  -c "SELECT id, retry_count, file_name, left(last_error, 200) FROM tasks WHERE status='FAILED' ORDER BY updated_at DESC LIMIT 20;"
```

## Schema Change Checklist

1. Update `db/repository.py:init_db()`.
2. Add idempotent migration to `db/repository.py:ensure_schema()`.
3. Update `config/settings.py:TASK_COLUMNS` if the field belongs to `TaskRow`.
4. Update `db/migrations.sql`.
5. Update this document.
