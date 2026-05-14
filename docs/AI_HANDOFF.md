# AI Handoff

This is the first file an AI coding agent should read after `README.md`.

## Project Summary

MinerU Scheduler is a Dockerized Python scheduler for bulk PDF parsing through MinerU. It scans PDFs into PostgreSQL, drives rows through a status machine, calls MinerU APIs, downloads result ZIP files, retries recoverable failures, splits over-limit PDFs, and persists local quota accounting so submission speed stays close to official MinerU limits.

SQLite has been removed. Do not reintroduce SQLite patterns.

## Read Order

1. `README.md`
2. `docs/AI_HANDOFF.md`
3. `docs/AI_FILE_MAP.md`
4. `docs/FLOW.md`
5. `docs/ARCHITECTURE.md`
6. `docs/DATABASE.md`
7. `docs/CONFIG.md`
8. Source file for the concrete task

## Highest-Value Files

| File | Why |
| --- | --- |
| `docker-compose.yml` | Runs PostgreSQL and scheduler together. |
| `Dockerfile` | Scheduler image definition. |
| `config/settings.py` | Env-driven config, PostgreSQL connection settings, quota constants, state machine. |
| `db/repository.py` | PostgreSQL connection, schema init, lock/update/insert functions. |
| `core/scheduler.py` | Main loop, page check, quota reservation, dispatch. |
| `core/quota_manager.py` | Daily quota and per-minute token bucket. |
| `handlers/upload_handler.py` | Upload batch creation and quota commit/release. |
| `scripts/scan_tasks.py` | PDF scan insertion into PostgreSQL. |

## Do Not Reintroduce

- `sqlite3`
- SQLite `.db` files
- `?` SQL placeholders
- `INSERT OR IGNORE`
- `AUTOINCREMENT`
- `cursor.executescript()`
- NAS-hosted database files

Use PostgreSQL/psycopg2:

- Placeholder: `%s`
- Conflict handling: `ON CONFLICT (...) DO NOTHING`
- Auto id: `BIGSERIAL`
- Lock batch: `UPDATE ... WHERE id = ANY(%s) RETURNING id`

## Current State Machine

Source of truth: `config/settings.py:VALID_TRANSITIONS`.

```text
INIT -> UPLOADED
INIT -> SPLIT_NEEDED
INIT -> FAILED
UPLOADED -> PUT_DONE
UPLOADED -> FAILED
PUT_DONE -> DOWNLOADING
PUT_DONE -> PUT_DONE
PUT_DONE -> FAILED
DOWNLOADING -> DOWNLOADED
DOWNLOADING -> FAILED
FAILED -> INIT
FAILED -> SPLIT_NEEDED
FAILED -> DEAD
FAILED -> FAILED
SPLIT_NEEDED -> SPLIT_DONE
SPLIT_NEEDED -> FAILED
SPLIT_NEEDED -> DEAD
```

## Quota Rules

| Rule | Implementation |
| --- | --- |
| 5000 files/day | PostgreSQL table `api_quota_usage.daily_files`. |
| Single file <= 200 pages | `Scheduler._prepare_init_tasks()` reads PDF pages. |
| High priority 1000 pages/day | PostgreSQL table `api_quota_usage.high_priority_pages`, local accounting only. |
| 50 files/minute | In-memory token bucket in `ApiQuotaManager`. |

Important: high-priority quota is currently only local accounting. Do not invent a MinerU API parameter without checking official docs.

## Critical Invariants

- Only unlocked tasks are scheduled: `locked = 0`.
- Handler completion must call `update_tasks()` or tasks remain locked.
- Scheduler releases tasks that were locked but not dispatched.
- Watchdog releases locks older than 300 seconds.
- `update_tasks()` rejects illegal status transitions.
- Quota reservations are committed only after MinerU upload batch creation succeeds.
- Quota reservations are released if local validation or upload batch creation fails.
- `file_path` is unique; repeated scans are idempotent.

## Common Change Recipes

### Add A Task Column

1. Update `db/repository.py:init_db()`.
2. Add idempotent migration in `db/repository.py:ensure_schema()`.
3. Update `config/settings.py:TASK_COLUMNS`.
4. Update `db/migrations.sql`.
5. Update `docs/DATABASE.md`.

### Add A Pipeline Status

1. Update `VALID_TRANSITIONS`.
2. Update `SCHEDULER_PRIORITY` if it should be scheduled.
3. Add handler and `core/dispatcher.py` mapping if needed.
4. Add per-status limit in `core/scheduler.py`.
5. Update `docs/FLOW.md`.

### Change PostgreSQL Queries

1. Use `%s` placeholders.
2. Pass sequences as `list(...)` for `ANY(%s)`.
3. Keep commits explicit.
4. Roll back if adding broad exception handling around DB writes.
5. Run compile check.

### Change Docker Runtime

1. Update `Dockerfile` or `docker-compose.yml`.
2. Update `.env.example`.
3. Update `README.md` and `docs/OPERATIONS.md`.

## Verification

```bash
python3 -m compileall core handlers db services scripts config utils main.py
git diff --check
```

Docker smoke check:

```bash
docker compose up -d --build
docker compose logs -f scheduler
```

## Known Risks

- The app is still designed as one scheduler instance. PostgreSQL removes NAS SQLite failures, but the per-minute quota bucket is process-local.
- `PollHandler` may poll the same `api_task_id` multiple times when tasks share a MinerU batch.
- Existing `.env` may contain real secrets. Do not print it in final answers.
