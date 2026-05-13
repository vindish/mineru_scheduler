# Architecture

MinerU Scheduler is organized as a small layered batch-processing system.

```text
main.py
  -> scripts.scan_tasks.scan_and_insert()
  -> monitor_loop()
  -> core.scheduler.Scheduler.run()
       -> db.repository.fetch_runnable_tasks()
       -> db.repository.lock_tasks()
       -> core.quota_manager.ApiQuotaManager
       -> core.worker_pool.WorkerPool.submit()
       -> core.dispatcher.Dispatcher.dispatch()
       -> handlers/*
       -> db.repository.update_tasks()
```

## Runtime Threads

| Thread | Owner | Responsibility |
| --- | --- | --- |
| Main thread | `Scheduler.run()` | Drives the scheduling loop forever. |
| Scanner daemon | `scan_loop()` in `main.py` | Periodically scans configured PDF directories and inserts `INIT` tasks. |
| Monitor daemon | `monitor_loop()` in `main.py` | Logs total, downloaded, and failed task counts. |
| Watchdog daemon | `core/watchdog.py` | Periodically releases stale locks. |
| Worker threads | `ThreadPoolExecutor` | Run handler batches. |

## Layer Responsibilities

### Config Layer

`config/settings.py` owns:

- MinerU URLs and token loading.
- Data paths.
- Official quota constants.
- Worker and per-stage concurrency settings.
- Retry and scan settings.
- State machine transitions.
- Initial task table SQL and column order.

### Core Layer

`core/scheduler.py` owns orchestration:

- Fetch runnable tasks.
- Lock candidate tasks.
- Group tasks by status.
- For `INIT`, read PDF page counts and reserve MinerU quota.
- Apply per-status batch limits.
- Submit handler work to `WorkerPool`.
- Release tasks that were locked but not dispatched.
- Emit heartbeat logs.

`core/dispatcher.py` owns status-to-handler routing.

`core/quota_manager.py` owns submission quota accounting:

- Persistent daily file count.
- Persistent local high-priority page count.
- In-memory per-minute token bucket.
- Pending reservation tracking.

`core/rate_limiter.py` owns simple per-stage QPS throttling.

`core/worker_pool.py` owns thread execution and backpressure.

`core/watchdog.py` owns stale lock cleanup.

### Handler Layer

Handlers are state-specific workers. They receive a list of `TaskRow`, mutate each task, then call `update_tasks()`.

| Handler | Input Status | Success Status | Main Work |
| --- | --- | --- | --- |
| `UploadHandler` | `INIT` | `UPLOADED` | Create MinerU upload batch and store `batch_id`/`upload_url`. |
| `PutHandler` | `UPLOADED` | `PUT_DONE` | PUT PDF bytes to MinerU-provided upload URL. |
| `PollHandler` | `PUT_DONE` | `DOWNLOADING` or `PUT_DONE` | Poll batch result and store `zip_url` when done. |
| `DownloadHandler` | `DOWNLOADING` | `DOWNLOADED` | Download ZIP to local storage. |
| `FailHandler` | `FAILED` | `INIT`, `SPLIT_NEEDED`, or `DEAD` | Route failures. |
| `SplitHandler` | `SPLIT_NEEDED` | `SPLIT_DONE` | Split PDF and create child `INIT` tasks. |

### Service Layer

`services/mineru_client.py` wraps HTTP calls:

- `create_upload_batch(files)`
- `upload_file(url, file_path)`
- `poll_batch(batch_id)`
- `download_stream(url)`

`services/storage.py` centralizes paths:

- DB path.
- Scan dirs.
- Split file paths.
- Download ZIP paths.
- Temp/output paths.

`services/pdf_splitter.py` uses PyPDF2 to split PDFs by page count.

### DB Layer

`db/repository.py` owns:

- Thread-local SQLite connections.
- WAL pragmas.
- Idempotent schema migration.
- Fetching runnable tasks.
- Locking and unlocking tasks.
- Validated task updates.
- Child task inserts.

`db/task_row.py` wraps SQLite rows with attribute-style access.

## Backpressure And Concurrency

There are three layers of throttling:

1. `WorkerPool` semaphore: limits queued/running work to roughly `MAX_WORKERS * 2`.
2. Scheduler per-status limits: caps how many tasks of each state are submitted per loop.
3. Rate limiters and quota manager: controls external API speed and official submission quota.

`MAX_DISPATCH_PER_ROUND` in `core/scheduler.py` is an additional safety cap to avoid flooding the executor in one loop.

## Error Containment

- Handler-level errors are usually converted into `FAILED` task updates.
- If a handler raises outside its internal error handling, `Dispatcher` logs and unlocks the batch.
- Watchdog releases locks older than 300 seconds.
- RetryHandler uses exponential backoff and eventually moves tasks to `DEAD`.

## Extension Points

- Add a new pipeline stage: add status, handler, dispatcher mapping, scheduler limit, docs.
- Change storage layout: update `services/storage.py`.
- Change MinerU API details: update `services/mineru_client.py` and affected handlers.
- Move to PostgreSQL: replace `db/repository.py` locking/update semantics and quota table implementation.
