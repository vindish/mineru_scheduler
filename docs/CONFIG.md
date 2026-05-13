# Configuration

All primary settings live in `config/settings.py`.

## Environment Variables

| Variable | Used By | Meaning |
| --- | --- | --- |
| `MINERU_TOKEN` | `TOKEN` | Bearer token for MinerU API. |
| `MINERU_DAILY_FILE_LIMIT` | `DAILY_FILE_LIMIT` | Override daily submission cap. |
| `MINERU_MAX_FILE_PAGES` | `MAX_FILE_PAGES` | Override single-file page cap. |
| `MINERU_HIGH_PRIORITY_DAILY_PAGE_LIMIT` | `HIGH_PRIORITY_DAILY_PAGE_LIMIT` | Override high-priority page quota. |
| `MINERU_SUBMIT_FILE_RATE_PER_MINUTE` | `SUBMIT_FILE_RATE_PER_MINUTE` | Override per-minute submission token rate. |

The project also loads `.env` if `python-dotenv` is installed.

## MinerU API Settings

| Setting | Current Value | Meaning |
| --- | --- | --- |
| `UPLOAD_URL` | `https://mineru.net/api/v4/file-urls/batch` | Create upload batch endpoint. |
| `POLL_URL` | `https://mineru.net/api/v4/extract-results/batch/` | Poll endpoint prefix. |
| `TOKEN` | `os.getenv("MINERU_TOKEN")` | Bearer token. |

`services/mineru_client.py` builds requests from these values.

## Path Settings

| Setting | Meaning |
| --- | --- |
| `BASE_DIR` | Root directory for runtime data. |
| `DB_NAME` | SQLite database file name under `BASE_DIR/db`. |
| `SCAN_DIRS` | Directories scanned for PDFs. |
| `LOG_DIR` | Log directory; currently `data/logs`. |

Important: `BASE_DIR` and `SCAN_DIRS` currently use absolute NAS paths. Change them when moving the project to another machine.

## Official Quota Settings

| Setting | Default | Meaning |
| --- | ---: | --- |
| `DAILY_FILE_LIMIT` | `5000` | Max submitted files per natural day. |
| `MAX_FILE_PAGES` | `200` | Max PDF pages per submitted file. |
| `HIGH_PRIORITY_DAILY_PAGE_LIMIT` | `1000` | Local high-priority page accounting limit. |
| `SUBMIT_FILE_RATE_PER_MINUTE` | `50` | File submission rate used by token bucket. |

Implementation:

- `MAX_FILE_PAGES` is enforced before upload batch creation.
- `DAILY_FILE_LIMIT` is persisted in SQLite table `api_quota_usage`.
- `SUBMIT_FILE_RATE_PER_MINUTE` is enforced in memory by `ApiQuotaManager`.
- `HIGH_PRIORITY_DAILY_PAGE_LIMIT` is tracked locally, but no API request parameter is currently sent.

## Worker And Batch Settings

| Setting | Current Value | Meaning |
| --- | ---: | --- |
| `MAX_WORKERS` | `12` | ThreadPoolExecutor worker count. |
| `FETCH_LIMIT` | `200` | Max tasks fetched per scheduler loop. |
| `BATCH_SIZE` | `50` | Max task count per handler batch slice. |
| `WATCHDOG_INTERVAL` | `60` | Watchdog interval in seconds. |

Scheduler also has local `MAX_DISPATCH_PER_ROUND = 100`.

## Per-Status Dispatch Limits

Defined in `core/scheduler.py` from settings:

| Status | Setting | Current Value |
| --- | --- | ---: |
| `FAILED` | `FAILED` | `5` |
| `SPLIT_NEEDED` | `SPLIT_NEEDED` | `5` |
| `DOWNLOADING` | `DOWNLOADING` | `20` |
| `PUT_DONE` | `POLL_CONCURRENCY` | `20` |
| `UPLOADED` | `PUT_CONCURRENCY` | `30` |
| `INIT` | `UPLOAD_CONCURRENCY` | `50` |

## QPS Settings

| Setting | Current Value | Used By |
| --- | ---: | --- |
| `QPS` | `2.0` | Shared limiter for split/fail paths. |
| `QPS_UPLOAD` | `1.0` | `UploadHandler` / create upload batch. |
| `QPS_PUT` | `10.0` | `PutHandler` / PUT upload. |
| `QPS_POLL` | `15.0` | `PollHandler` / poll API. |
| `QPS_DOWNLOAD` | `5.0` | `DownloadHandler` / download stream. |

`RateLimiter.adjust()` can increase or decrease QPS based on recent failure rate.

## Retry Settings

| Setting | Current Value | Meaning |
| --- | ---: | --- |
| `MAX_RETRY` | `5` | Max retry attempts before `DEAD`. |
| `RETRY_DELAY` | `60` | Legacy setting; current retry uses `exponential_backoff()`. |

## Scan Settings

| Setting | Current Value | Meaning |
| --- | ---: | --- |
| `SCAN_INTERVAL` | `60` | Seconds between scan loops. |
| `SCAN_MAX_FILES` | `200000` | Max PDF files scanned per pass. |
| `SCAN_BATCH_SLEEP` | `0.01` | Sleep every 200 scanned files. |

## State Settings

`SCHEDULER_PRIORITY` controls scheduling order.

`VALID_TRANSITIONS` controls legal status updates. `db.repository.update_tasks()` rejects invalid transitions and logs `[INVALID TRANSITION]`.

When adding or changing statuses, update:

- `VALID_TRANSITIONS`
- `SCHEDULER_PRIORITY`
- `core/dispatcher.py`
- `core/scheduler.py` limit map
- `docs/FLOW.md`
