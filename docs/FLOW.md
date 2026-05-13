# Task Flow

This document describes the task lifecycle at the level needed to debug or modify the scheduler.

## Happy Path

```text
PDF on disk
  -> scan_and_insert()
  -> tasks row with status INIT
  -> Scheduler locks row
  -> Scheduler reads page_count
  -> Scheduler reserves MinerU quota
  -> UploadHandler.create_upload_batch()
  -> status UPLOADED
  -> PutHandler.upload_file()
  -> status PUT_DONE
  -> PollHandler.poll_batch()
  -> status DOWNLOADING when MinerU state is done
  -> DownloadHandler.download_stream()
  -> status DOWNLOADED
```

## Scan Stage

Owner: `scripts/scan_tasks.py`

Behavior:

- Reads directories from `Storage.get_scan_dirs()`.
- Recursively finds `*.pdf`.
- Converts file paths to absolute paths.
- Inserts `file_path`, `file_name`, `status='INIT'`, `created_at`.
- Uses `INSERT OR IGNORE`, relying on the unique `file_path` index.

Important settings:

- `SCAN_DIRS`
- `SCAN_INTERVAL`
- `SCAN_MAX_FILES`
- `SCAN_BATCH_SLEEP`

## Scheduling Stage

Owner: `core/scheduler.py`

Each loop:

1. `fetch_runnable_tasks(FETCH_LIMIT)` returns unlocked, non-terminal tasks whose `next_run_time` is due.
2. `lock_tasks()` marks candidate rows as locked.
3. Tasks are grouped by `status`.
4. Status groups are processed in `SCHEDULER_PRIORITY` order.
5. Per-status limits are applied.
6. For `INIT`, `_prepare_init_tasks()` runs page and quota checks.
7. Batches are submitted to `WorkerPool`.
8. Locked but undispatched tasks are unlocked.

Current priority:

```text
FAILED
SPLIT_NEEDED
DOWNLOADING
PUT_DONE
UPLOADED
INIT
```

This means cleanup and continuation work run before new submissions.

## INIT Preparation

Owner: `Scheduler._prepare_init_tasks()`

For each `INIT` task:

1. Read `page_count` from row if already set.
2. Otherwise load the PDF with PyPDF2 and count pages.
3. If pages exceed `MAX_FILE_PAGES`, set:

```text
status = SPLIT_NEEDED
last_error = "page count ... exceeds limit ..."
```

4. If page count fails, set:

```text
status = FAILED
last_error = "read page count failed: ..."
```

5. For valid PDFs, call `ApiQuotaManager.reserve_submission_batch()`.
6. If quota is unavailable, set `next_run_time` and unlock the task.
7. Return only quota-approved tasks to dispatch.

## Upload Stage

Owner: `handlers/upload_handler.py`

Input: `INIT`

Work:

- Validate file path exists.
- Build MinerU batch payload:

```json
{
  "files": [
    {"name": "file.pdf", "data_id": "task_id"}
  ],
  "model_version": "vlm"
}
```

- Call `MineruClient.create_upload_batch()`.
- Store returned `batch_id` in `api_task_id`.
- Store returned upload URL in `upload_url`.
- Move task to `UPLOADED`.
- Commit quota reservations only after the batch call succeeds.

Failure:

- Release quota reservations.
- Usually move valid tasks to `FAILED`.
- If error includes `expired`, reset task to `INIT` and clear `upload_url`.

## PUT Stage

Owner: `handlers/put_handler.py`

Input: `UPLOADED`

Work:

- Validate file exists.
- Validate `upload_url`.
- PUT file bytes to URL.
- Move task to `PUT_DONE`.

Failure:

- Move task to `FAILED`.
- Store `last_error`.

## Poll Stage

Owner: `handlers/poll_handler.py`

Input: `PUT_DONE`

Work:

- Call `MineruClient.poll_batch(batch_id)`.
- Read `data.extract_result`.
- Match item by `file_name`.
- If `state == done`, move to `DOWNLOADING` and store `full_zip_url` as `zip_url`.
- If `state == failed`, move to `FAILED`.
- Otherwise remain `PUT_DONE`.

Potential inefficiency:

- Multiple tasks in the same MinerU batch may each poll the same `batch_id`.

## Download Stage

Owner: `handlers/download_handler.py`

Input: `DOWNLOADING`

Work:

- Validate `zip_url`.
- Build stable download path through `Storage.get_download_path()`.
- Skip existing ZIP if size > 1024 bytes.
- Download stream and write to disk.
- Move to `DOWNLOADED`.

Failure:

- Move to `FAILED`.
- Store truncated `last_error`.

## Failure Stage

Owner: `handlers/fail_handler.py`

Input: `FAILED`

Routing:

| Error Pattern | Result |
| --- | --- |
| contains `exceeds limit` | `SPLIT_NEEDED` |
| contains `file not found` or `invalid pdf` | `DEAD` |
| contains `429` | Retry |
| other | Retry |

Retry owner: `handlers/retry_handler.py`

Retry behavior:

- If `retry_count >= MAX_RETRY`, move to `DEAD`.
- Otherwise move to `INIT`, increment `retry_count`, set `next_run_time` using exponential backoff.

Dead-letter owner: `task_queue/dlq.py`

Dead behavior:

- Set `status='DEAD'`.
- Set `error_type`.
- Set `dead_at`.

## Split Stage

Owner: `handlers/split_handler.py`

Input: `SPLIT_NEEDED`

Work:

- Use `PDFSplitter` with `max_pages=MAX_FILE_PAGES`.
- If no split is needed, move original task to `SPLIT_DONE`.
- If split is needed:
  - Write child PDFs under split storage.
  - Insert child tasks as `INIT`.
  - Set child `parent_id` to original task id.
  - Move original task to `SPLIT_DONE`.

## Terminal States

Terminal states are excluded by `fetch_runnable_tasks()`:

```text
DEAD
DOWNLOADED
SPLIT_DONE
```

## Lock Lifecycle

```text
fetch_runnable_tasks()
  -> lock_tasks()
  -> handler update_tasks()
  -> locked = 0, locked_at = NULL
```

If a task is locked but not dispatched in the current loop, scheduler calls `unlock_tasks()`.

If a worker dies or a process exits while tasks are locked, Watchdog calls `heal_locks(timeout=300)`.
