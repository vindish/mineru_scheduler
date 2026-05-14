# Task Flow

This document describes the PostgreSQL-backed task lifecycle.

## Happy Path

```text
PDF file in /app/data/pdf
  -> scan_and_insert()
  -> INSERT tasks(status='INIT') ON CONFLICT DO NOTHING
  -> Scheduler fetches runnable tasks
  -> Scheduler locks rows in PostgreSQL
  -> Scheduler checks page_count and reserves quota
  -> UploadHandler creates MinerU upload batch
  -> UPLOADED
  -> PutHandler PUTs file bytes
  -> PUT_DONE
  -> PollHandler polls MinerU batch
  -> DOWNLOADING
  -> DownloadHandler downloads ZIP
  -> DOWNLOADED
```

## Scan

Owner: `scripts/scan_tasks.py`

Behavior:

- Reads `SCAN_DIRS`.
- Finds `*.pdf` recursively.
- Inserts absolute file paths into PostgreSQL.
- Uses `ON CONFLICT (file_path) DO NOTHING` for idempotency.

Inserted fields:

```text
file_path
file_name
status = INIT
created_at
```

## Fetch And Lock

Owner: `db/repository.py`

Runnable query:

```sql
SELECT *
FROM tasks
WHERE locked = 0
AND status NOT IN ('DEAD', 'DOWNLOADED', 'SPLIT_DONE')
AND (next_run_time IS NULL OR next_run_time <= %s)
ORDER BY id
LIMIT %s;
```

Lock query:

```sql
UPDATE tasks
SET locked = 1, locked_at = %s
WHERE id = ANY(%s)
AND locked = 0
RETURNING id;
```

Only returned ids are considered locked by this scheduler loop.

## INIT Preparation

Owner: `core/scheduler.py:_prepare_init_tasks()`

For each `INIT` task:

1. Use cached `page_count` if present.
2. Otherwise read PDF page count with PyPDF2.
3. If pages exceed `MAX_FILE_PAGES`, move to `SPLIT_NEEDED`.
4. If PDF reading fails, move to `FAILED`.
5. For valid files, reserve quota through `ApiQuotaManager`.
6. If quota is unavailable, set `next_run_time` and unlock.

Only quota-approved tasks are dispatched to `UploadHandler`.

## Upload

Owner: `handlers/upload_handler.py`

Input: `INIT`

MinerU request body:

```json
{
  "files": [
    {"name": "file.pdf", "data_id": "task_id"}
  ],
  "model_version": "vlm"
}
```

Success:

- Store MinerU batch id in `api_task_id`.
- Store returned upload URL in `upload_url`.
- Move to `UPLOADED`.
- Commit quota reservation.

Failure:

- Release quota reservation.
- Move task to `FAILED`, or reset to `INIT` if URL expiration requires a new upload URL.

## PUT Upload

Owner: `handlers/put_handler.py`

Input: `UPLOADED`

Success:

- PUT PDF bytes to `upload_url`.
- Move to `PUT_DONE`.

Failure:

- Move to `FAILED`.

## Poll

Owner: `handlers/poll_handler.py`

Input: `PUT_DONE`

Success:

- Call MinerU poll endpoint by `api_task_id`.
- Match result item by `file_name`.
- If state is `done`, store `full_zip_url` as `zip_url` and move to `DOWNLOADING`.
- If state is still processing, remain `PUT_DONE`.

Failure:

- Move to `FAILED`.

## Download

Owner: `handlers/download_handler.py`

Input: `DOWNLOADING`

Success:

- Download `zip_url` to `BASE_DIR/download`.
- Move to `DOWNLOADED`.

Failure:

- Move to `FAILED`.

## Failure Routing

Owner: `handlers/fail_handler.py`

| Error | Route |
| --- | --- |
| contains `exceeds limit` | `SPLIT_NEEDED` |
| contains `file not found` | `DEAD` |
| contains `invalid pdf` | `DEAD` |
| contains `429` | retry |
| other | retry |

Retry owner: `handlers/retry_handler.py`

Retry:

- If `retry_count >= MAX_RETRY`, move to `DEAD`.
- Otherwise move to `INIT`, increment retry count, and set `next_run_time`.

## Split

Owner: `handlers/split_handler.py`

Input: `SPLIT_NEEDED`

Behavior:

- Split source PDF into chunks of at most `MAX_FILE_PAGES`.
- Insert child tasks with `status='INIT'` and `parent_id`.
- Move original task to `SPLIT_DONE`.

## Terminal States

These states are not fetched again:

```text
DEAD
DOWNLOADED
SPLIT_DONE
```

## Unlock Paths

Normal:

```text
handler -> update_tasks() -> locked = 0, locked_at = NULL
```

Dispatch error:

```text
Dispatcher exception -> unlock_tasks()
```

Not dispatched:

```text
Scheduler locked too many -> unlock_tasks()
```

Timeout:

```text
Watchdog -> heal_locks(timeout=300)
```
