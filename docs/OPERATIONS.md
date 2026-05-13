# Operations

This document covers running, checking, and debugging the scheduler.

## First Run Checklist

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. Set MinerU token:

```bash
export MINERU_TOKEN="your-token"
```

3. Confirm paths in `config/settings.py`:

```text
BASE_DIR
SCAN_DIRS
DB_NAME
```

4. Put PDFs under one of the configured `SCAN_DIRS`.

5. Start:

```bash
python3 main.py
```

## Routine Verification

Compile check:

```bash
python3 -m compileall core handlers db services config utils main.py
```

Whitespace/diff check:

```bash
git diff --check
```

Git status:

```bash
git status --short
```

## Logs To Watch

Common log prefixes:

| Prefix | Meaning |
| --- | --- |
| `[SCAN]` | Scanner progress and insert count. |
| `[SCHEDULER]` | Fetched/locked task counts and queue status. |
| `[DISPATCH]` | Handler dispatch by status. |
| `[HEARTBEAT]` | Queue, QPS, success/fail, quota remaining. |
| `[QUOTA]` | Reservation commit/release/defer events. |
| `[PAGE-CHECK]` | Page-count routing to split or failed. |
| `[UPLOAD]` | Upload batch creation. |
| `[PUT FAIL]` | PUT upload failure. |
| `[POLL]` | Poll progress. |
| `[DOWNLOAD OK]` | Successful ZIP download. |
| `[DOWNLOAD FAIL]` | Download failure. |
| `[WATCHDOG]` | Stale lock cleanup. |
| `[INVALID TRANSITION]` | State machine rejected an update. |

## Database Inspection

Open DB:

```bash
sqlite3 /path/to/tasks1.db
```

Task status counts:

```sql
SELECT status, COUNT(*) FROM tasks GROUP BY status;
```

Quota today:

```sql
SELECT * FROM api_quota_usage ORDER BY quota_date DESC LIMIT 1;
```

Locked tasks:

```sql
SELECT id, status, locked_at, file_name FROM tasks WHERE locked=1;
```

Failed tasks:

```sql
SELECT id, retry_count, file_name, last_error
FROM tasks
WHERE status='FAILED'
ORDER BY updated_at DESC
LIMIT 20;
```

## Common Issues

### No Tasks Are Running

Check:

- Are PDFs under `SCAN_DIRS`?
- Does `SCAN_DIRS` point to the current machine path?
- Are tasks locked?
- Are tasks delayed by `next_run_time`?
- Is daily quota exhausted?

Useful SQL:

```sql
SELECT status, locked, COUNT(*) FROM tasks GROUP BY status, locked;
SELECT COUNT(*) FROM tasks WHERE next_run_time > strftime('%s', 'now');
SELECT * FROM api_quota_usage ORDER BY quota_date DESC LIMIT 1;
```

### Tasks Stuck Locked

Watchdog should release locks older than 300 seconds.

Manual inspection:

```sql
SELECT id, status, locked_at, file_name
FROM tasks
WHERE locked=1
ORDER BY locked_at;
```

If needed, use project repair logic or carefully update locks after confirming no worker is still running.

### Many INVALID TRANSITION Logs

Cause:

- Handler is trying a status change missing from `VALID_TRANSITIONS`.
- Existing DB status does not match expected in-memory status.

Fix path:

1. Inspect old and new status from logs.
2. Confirm if transition is valid in the lifecycle.
3. Update `VALID_TRANSITIONS` only if valid.
4. Otherwise fix the handler logic.

### Upload Quota Seems Exhausted

Check quota table:

```sql
SELECT * FROM api_quota_usage ORDER BY quota_date DESC LIMIT 5;
```

Check future-delayed INIT tasks:

```sql
SELECT COUNT(*), MIN(next_run_time), MAX(next_run_time)
FROM tasks
WHERE status='INIT'
AND next_run_time IS NOT NULL;
```

Expected behavior:

- If daily file quota is exhausted, INIT tasks are delayed until next local day.
- If minute tokens are exhausted, INIT tasks are delayed by a short wait.

### PDFs Over 200 Pages

Expected behavior:

- Scheduler marks them `SPLIT_NEEDED`.
- SplitHandler creates child PDFs under split directory.
- Original task becomes `SPLIT_DONE`.
- Child tasks enter `INIT`.

Check:

```sql
SELECT id, status, page_count, file_name, last_error
FROM tasks
WHERE page_count > 200 OR status='SPLIT_NEEDED';
```

### Polling Is Slow Or Repetitive

Current behavior polls per task, even if several tasks share one `api_task_id`.

Possible future improvement:

- Batch poll once per `api_task_id`.
- Fan out result updates to all tasks in the same batch.

## Safe Manual Recovery Examples

Retry failed tasks by letting existing failure handler route them:

```sql
UPDATE tasks
SET locked=0, locked_at=NULL, next_run_time=NULL
WHERE status='FAILED';
```

Release stale locks after confirming process is stopped:

```sql
UPDATE tasks
SET locked=0, locked_at=NULL
WHERE locked=1;
```

Reset a specific task to INIT:

```sql
UPDATE tasks
SET status='INIT',
    locked=0,
    locked_at=NULL,
    next_run_time=NULL,
    retry_count=0,
    last_error=NULL
WHERE id=?;
```

Do not mass reset `DOWNLOADED` unless you intentionally want to redownload/reprocess.

## Performance Tuning

Start with these settings:

- `MAX_WORKERS`
- `FETCH_LIMIT`
- `BATCH_SIZE`
- `UPLOAD_CONCURRENCY`
- `PUT_CONCURRENCY`
- `POLL_CONCURRENCY`
- `DOWNLOADING`
- `QPS_*`

For MinerU submission throughput, the main gate is:

```text
SUBMIT_FILE_RATE_PER_MINUTE = 50
DAILY_FILE_LIMIT = 5000
```

Increasing worker count cannot bypass these limits. It only helps keep PUT, poll, and download stages from falling behind.

## Before Shipping Changes

Run:

```bash
python3 -m compileall core handlers db services config utils main.py
git diff --check
```

Then inspect:

```bash
git diff --stat
git diff
```
