# AI File Map

This file is a compact map for agents that need to locate code quickly.

## Entrypoints

| Path | Role |
| --- | --- |
| `main.py` | Starts the whole process. |
| `run.bat` | Windows launcher. |
| `scripts/scan_tasks.py` | Can be read to understand scan insertion. |

## Core Scheduling

| Path | Read When |
| --- | --- |
| `core/scheduler.py` | Anything about task order, quota before upload, locking, batching, heartbeat. |
| `core/dispatcher.py` | Need to know which handler owns a status. |
| `core/quota_manager.py` | MinerU file/day, high-priority page, file/minute behavior. |
| `core/rate_limiter.py` | Per-stage QPS behavior. |
| `core/worker_pool.py` | Thread pool and backpressure. |
| `core/watchdog.py` | Locked task recovery. |

## Handlers

| Path | Status |
| --- | --- |
| `handlers/upload_handler.py` | `INIT` |
| `handlers/put_handler.py` | `UPLOADED` |
| `handlers/poll_handler.py` | `PUT_DONE` |
| `handlers/download_handler.py` | `DOWNLOADING` |
| `handlers/fail_handler.py` | `FAILED` |
| `handlers/retry_handler.py` | Retry from `FAILED` |
| `handlers/split_handler.py` | `SPLIT_NEEDED` |

## Services

| Path | Role |
| --- | --- |
| `services/mineru_client.py` | External HTTP calls to MinerU and upload/download URLs. |
| `services/storage.py` | Runtime path generation. |
| `services/pdf_splitter.py` | Splitting PDFs into <= configured page count. |
| `services/file_watcher.py` | File watching extension area. |

## Database

| Path | Role |
| --- | --- |
| `db/repository.py` | SQLite connection, migrations, locks, updates, inserts. |
| `db/task_row.py` | Mutable row wrapper. |
| `db/migrations.sql` | Schema reference. |
| `db/update_buffer.py` | Future buffering extension. |

## Utilities

| Path | Role |
| --- | --- |
| `utils/logger.py` | Logging config. |
| `utils/startup_check.py` | Startup validation. |
| `utils/backoff.py` | Exponential retry delay. |
| `utils/decorators.py` | `with_rate_limit` decorator. |
| `utils/time_utils.py` | Time helper. |

## Scripts And SQL

| Path | Role |
| --- | --- |
| `scripts/repair_tasks.py` | Repair helper. |
| `scripts/reset_tasks.sql` | Manual reset SQL. |
| `scripts/retry_failed.sql` | Manual retry SQL. |

## Docs

| Path | Purpose |
| --- | --- |
| `README.md` | Main overview. |
| `docs/AI_HANDOFF.md` | AI onboarding. |
| `docs/ARCHITECTURE.md` | Module architecture. |
| `docs/FLOW.md` | Task lifecycle. |
| `docs/CONFIG.md` | Settings and tuning. |
| `docs/DATABASE.md` | Schema and SQL. |
| `docs/OPERATIONS.md` | Runbook. |
