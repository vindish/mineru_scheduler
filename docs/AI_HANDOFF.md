# AI Handoff

This document is optimized for an AI coding agent that needs to enter the project quickly.

## Project In One Paragraph

MinerU Scheduler is a single-machine Python + SQLite scheduler for bulk PDF parsing through MinerU. It scans PDF files into a `tasks` table, drives them through a status machine, calls MinerU APIs, downloads result ZIP files, retries recoverable failures, splits PDFs over the page limit, and keeps local quota accounting to run close to official MinerU limits.

## Read Order

1. `README.md`: product-level summary and quick commands.
2. `docs/AI_HANDOFF.md`: this file.
3. `docs/FLOW.md`: exact lifecycle and failure paths.
4. `docs/ARCHITECTURE.md`: module ownership and call graph.
5. `docs/DATABASE.md`: schema, locks, migrations.
6. `docs/CONFIG.md`: tuning knobs and quota settings.
7. Relevant source file for the concrete task.

## Current Important Files

| File | Why It Matters |
| --- | --- |
| `main.py` | Process entrypoint; starts schema init, scanner, monitor, scheduler. |
| `config/settings.py` | Central config, official quota constants, state machine. |
| `core/scheduler.py` | Main loop; locks tasks, groups by status, checks pages, reserves quota, dispatches batches. |
| `core/quota_manager.py` | Daily and per-minute MinerU quota guardrail. |
| `core/dispatcher.py` | Maps task status to handler. |
| `handlers/upload_handler.py` | Creates MinerU upload batch and commits/releases quota reservations. |
| `handlers/put_handler.py` | Uploads PDFs to returned OSS upload URLs. |
| `handlers/poll_handler.py` | Polls MinerU batch results. |
| `handlers/download_handler.py` | Downloads result ZIP files. |
| `handlers/fail_handler.py` | Routes failures to retry, split, or dead letter. |
| `handlers/split_handler.py` | Splits large PDFs and inserts child tasks. |
| `db/repository.py` | SQLite connection, migrations, locking, updates. |
| `db/task_row.py` | Task row wrapper used by handlers and repository. |
| `services/mineru_client.py` | MinerU HTTP wrapper. |
| `services/storage.py` | Data directory and path generation. |
| `scripts/scan_tasks.py` | PDF scanner that inserts `INIT` tasks. |

## Current State Machine

```text
INIT -> UPLOADED -> PUT_DONE -> DOWNLOADING -> DOWNLOADED
INIT -> SPLIT_NEEDED -> SPLIT_DONE
INIT -> FAILED
UPLOADED -> FAILED
PUT_DONE -> FAILED
DOWNLOADING -> FAILED
FAILED -> INIT
FAILED -> SPLIT_NEEDED
FAILED -> DEAD
```

Source of truth: `config/settings.py:VALID_TRANSITIONS`.

## MinerU Quota Rules Implemented Locally

| Rule | Implementation |
| --- | --- |
| 5000 files/day | `api_quota_usage.daily_files`, guarded by `ApiQuotaManager`. |
| Single file <= 200 pages | `Scheduler._prepare_init_tasks()` reads pages; over-limit tasks go to `SPLIT_NEEDED`. |
| High priority 1000 pages/day | `api_quota_usage.high_priority_pages`, local accounting only. |
| 50 files/minute | In-memory token bucket in `ApiQuotaManager`. |

Important caveat: there is currently no official high-priority request parameter in this codebase. Do not invent one without confirming MinerU API docs.

## Critical Invariants

- Only unlocked tasks are fetched: `locked=0`.
- Dispatcher/handlers must eventually call `update_tasks()` or `unlock_tasks()` to release locks.
- `update_tasks()` validates status transitions. If a new transition is needed, update `VALID_TRANSITIONS`.
- `TaskRow` objects are mutable; handlers mutate fields and pass the objects into `update_tasks()`.
- `file_path` has a unique index. Duplicate scans are ignored.
- Split child tasks are separate `INIT` tasks with `parent_id` set.
- Quota reservation must be committed only after MinerU upload batch creation succeeds.
- Quota reservation must be released if upload batch creation fails or local upload validation rejects files.

## Common Change Recipes

### Add A New Task Status

1. Add the status to `VALID_TRANSITIONS`.
2. Add its position to `SCHEDULER_PRIORITY` if it should be scheduled.
3. Add a handler in `core/dispatcher.py` if it needs processing.
4. Add per-round limit in `core/scheduler.py` `limit_map`.
5. Update `docs/FLOW.md` and `docs/DATABASE.md`.

### Change MinerU Request Shape

1. Edit `services/mineru_client.py`.
2. Check all handlers using the modified client method.
3. If submission semantics change, update `core/quota_manager.py`.
4. Update `README.md` and `docs/CONFIG.md`.

### Change Quota Behavior

1. Start in `core/quota_manager.py`.
2. Check `Scheduler._prepare_init_tasks()`.
3. Check `UploadHandler.handle_batch()` commit/release paths.
4. Run `python3 -m compileall core handlers db services config utils main.py`.

### Change DB Schema

1. Update `config/settings.py:INIT_SQL`.
2. Update `config/settings.py:TASK_COLUMNS` if the field belongs to `tasks`.
3. Add an idempotent migration in `db/repository.py:ensure_schema()`.
4. Update `db/migrations.sql`.
5. Update `docs/DATABASE.md`.

## Verification Commands

```bash
python3 -m compileall core handlers db services config utils main.py
git diff --check
```

If running the scheduler for real, make sure `MINERU_TOKEN`, `BASE_DIR`, and `SCAN_DIRS` are correct before starting:

```bash
python3 main.py
```

## Known Risks

- SQLite is protected by a Python `threading.Lock`, but it is not a distributed lock.
- The minute token bucket is process-local. A restart resets minute tokens but does not reset daily quota usage.
- `BASE_DIR` and `SCAN_DIRS` are currently absolute NAS paths.
- `PollHandler` polls by `batch_id` for each task; tasks sharing a batch may duplicate poll calls.
- Some older comments in the code are stale. Trust code behavior first, then docs.
