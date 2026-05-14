# Architecture

MinerU Scheduler is a Dockerized single-scheduler application backed by PostgreSQL.

```text
docker compose
  ├─ postgres
  └─ scheduler
       -> main.py
       -> scan_loop()
       -> monitor_loop()
       -> Scheduler.run()
            -> PostgreSQL fetch/lock
            -> page check
            -> quota reservation
            -> WorkerPool
            -> Dispatcher
            -> Handler
            -> PostgreSQL update/unlock
```

## Containers

| Service | Image | Role |
| --- | --- | --- |
| `postgres` | `postgres:16-alpine` | Stores tasks and quota usage. |
| `scheduler` | Local `Dockerfile` | Runs scanner, monitor, watchdog, and scheduler. |

Runtime files are mounted with:

```text
./data:/app/data
```

PostgreSQL data is stored in Docker volume:

```text
postgres_data
```

## Runtime Threads

| Thread | Owner | Responsibility |
| --- | --- | --- |
| Main | `Scheduler.run()` | Main scheduling loop. |
| Scanner daemon | `main.scan_loop()` | Periodically scans PDFs and inserts `INIT` tasks. |
| Monitor daemon | `main.monitor_loop()` | Logs task counts. |
| Watchdog daemon | `core/watchdog.py` | Releases stale locks. |
| Worker threads | `core/worker_pool.py` | Execute handler batches. |

## Layer Responsibilities

### Config

`config/settings.py` owns:

- MinerU token and URLs.
- PostgreSQL connection settings.
- Runtime data paths.
- Official quota constants.
- Worker and batch limits.
- Status priority and valid transitions.
- Task column list.

### Core

`core/scheduler.py` owns:

- Fetching runnable tasks.
- Locking tasks.
- Grouping by status.
- Page-count checks for `INIT`.
- Quota reservation before upload batch creation.
- Per-status dispatch limits.
- Releasing locked but undispatched tasks.
- Heartbeat logging.

`core/quota_manager.py` owns:

- Daily quota persisted in PostgreSQL.
- High-priority page usage persisted in PostgreSQL.
- In-memory per-minute token bucket.
- Pending reservation tracking.

`core/dispatcher.py` maps task status to handler.

`core/rate_limiter.py` provides per-stage QPS throttling.

`core/worker_pool.py` wraps `ThreadPoolExecutor` and provides backpressure.

`core/watchdog.py` periodically calls `heal_locks()`.

### Handlers

| Handler | Input | Success |
| --- | --- | --- |
| `UploadHandler` | `INIT` | `UPLOADED` |
| `PutHandler` | `UPLOADED` | `PUT_DONE` |
| `PollHandler` | `PUT_DONE` | `DOWNLOADING` or `PUT_DONE` |
| `DownloadHandler` | `DOWNLOADING` | `DOWNLOADED` |
| `FailHandler` | `FAILED` | `INIT`, `SPLIT_NEEDED`, or `DEAD` |
| `SplitHandler` | `SPLIT_NEEDED` | `SPLIT_DONE` |

Handlers mutate `TaskRow` objects and persist through `db.repository.update_tasks()`.

### Database

`db/repository.py` owns all PostgreSQL access:

- `get_conn()`
- `init_db()`
- `ensure_schema()`
- `fetch_runnable_tasks()`
- `lock_tasks()`
- `unlock_tasks()`
- `update_tasks()`
- `insert_tasks()`
- `heal_locks()`

Implementation details:

- Driver: `psycopg2`.
- Cursor: `RealDictCursor`.
- Thread-local connection per Python thread.
- Python `db_lock` still serializes writes in this single-process app.

### Services

`services/mineru_client.py` wraps MinerU HTTP.

`services/storage.py` owns runtime paths under `BASE_DIR`.

`services/pdf_splitter.py` splits PDFs with PyPDF2.

## Backpressure

The system has multiple gates:

1. `MAX_WORKERS`: thread count.
2. `WorkerPool` semaphore: limits queued and running work.
3. Scheduler per-status limits.
4. QPS rate limiters.
5. `ApiQuotaManager`: official submission quota guard.

Raising thread count alone does not bypass MinerU submission quota.

## Error Containment

- Handler-specific failures usually become `FAILED`.
- Unexpected dispatcher errors unlock the current batch.
- Watchdog releases stale locks older than 300 seconds.
- RetryHandler uses exponential backoff and eventually moves tasks to `DEAD`.

## Scaling Boundary

PostgreSQL makes the DB suitable for NAS/Docker usage, but the app is still designed for one scheduler instance. Running multiple scheduler containers needs redesign of the in-memory token bucket and stronger distributed quota semantics.
