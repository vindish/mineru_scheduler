# AI File Map

Compact file map for fast code navigation.

## Runtime And Docker

| Path | Role |
| --- | --- |
| `Dockerfile` | Builds scheduler image. |
| `docker-compose.yml` | Runs PostgreSQL and scheduler. |
| `.env.example` | Required environment template. |
| `.dockerignore` | Keeps data/secrets out of image build context. |
| `main.py` | Process entrypoint. |

## Config

| Path | Role |
| --- | --- |
| `config/settings.py` | MinerU settings, PostgreSQL settings, paths, quota, concurrency, state machine. |

## Core

| Path | Read When |
| --- | --- |
| `core/scheduler.py` | Scheduling order, page checks, quota reservation, dispatch. |
| `core/dispatcher.py` | Status-to-handler mapping. |
| `core/quota_manager.py` | Daily quota, high-priority pages, per-minute token bucket. |
| `core/rate_limiter.py` | Per-stage QPS logic. |
| `core/worker_pool.py` | Thread pool and backpressure. |
| `core/watchdog.py` | Stale lock recovery. |

## Database

| Path | Role |
| --- | --- |
| `db/repository.py` | PostgreSQL connection, schema, locks, updates, inserts. |
| `db/task_row.py` | Mutable row wrapper. |
| `db/migrations.sql` | PostgreSQL schema reference. |
| `db/update_buffer.py` | Future buffering extension. |

## Handlers

| Path | Input Status |
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
| `services/mineru_client.py` | MinerU HTTP API wrapper. |
| `services/storage.py` | Runtime file paths under `BASE_DIR`. |
| `services/pdf_splitter.py` | PDF splitting. |
| `services/file_watcher.py` | Optional file watcher insertion. |

## Scripts

| Path | Role |
| --- | --- |
| `scripts/scan_tasks.py` | Scans PDFs and inserts `INIT` tasks into PostgreSQL. |
| `scripts/repair_tasks.py` | Repair helper. |
| `scripts/reset_tasks.sql` | Manual reset SQL; review before using. |
| `scripts/retry_failed.sql` | Manual retry SQL; review before using. |

## Docs

| Path | Purpose |
| --- | --- |
| `README.md` | Main overview and quick start. |
| `docs/AI_HANDOFF.md` | AI onboarding. |
| `docs/ARCHITECTURE.md` | Module architecture. |
| `docs/FLOW.md` | Task lifecycle. |
| `docs/CONFIG.md` | Config and tuning. |
| `docs/DATABASE.md` | PostgreSQL schema and queries. |
| `docs/OPERATIONS.md` | Docker runbook. |
