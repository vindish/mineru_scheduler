# Configuration

Configuration is environment-driven and loaded by `config/settings.py`. Docker Compose reads `.env`.

## Required

| Variable | Meaning |
| --- | --- |
| `MINERU_TOKEN` | MinerU API bearer token. |

## Docker Compose PostgreSQL

| Variable | Default | Meaning |
| --- | --- | --- |
| `POSTGRES_DB` | `mineru_scheduler` | Database name. |
| `POSTGRES_USER` | `mineru` | Database user. |
| `POSTGRES_PASSWORD` | `mineru_password` | Database password. Change it. |

Inside Compose, scheduler connects to host `postgres`.

## App PostgreSQL Connection

| Variable | Default | Meaning |
| --- | --- | --- |
| `DATABASE_URL` | empty | Full psycopg2 connection URL. If set, overrides individual PG settings. |
| `POSTGRES_HOST` | `postgres` | DB host. |
| `POSTGRES_PORT` | `5432` | DB port. |
| `POSTGRES_DB` | `mineru_scheduler` | DB name. |
| `POSTGRES_USER` | `mineru` | DB user. |
| `POSTGRES_PASSWORD` | `mineru_password` | DB password. |

## Runtime Paths

All input PDF sources and output destinations are centralized in
[config/settings.py](../config/settings.py) so any module can import them.
Environment variables override defaults and accept comma-separated lists where
applicable.

| Variable | Default | Meaning |
| --- | --- | --- |
| `BASE_DIR` | `<project>/data` (or `/app/data` in Compose) | Runtime data root. |
| `PDF_INPUT_DIRS` | `${BASE_DIR}/pdf` | Comma-separated list of PDF source directories. Old name `SCAN_DIRS` is still accepted. |
| `OUTPUT_BASE_DIR` | `${BASE_DIR}` | Root for all outputs. |
| `DOWNLOAD_DIR` | `${OUTPUT_BASE_DIR}/download` | Result ZIPs downloaded from MinerU. |
| `OUTPUT_DIR` | `${OUTPUT_BASE_DIR}/output` | Parsed output files. |
| `SPLIT_DIR` | `${OUTPUT_BASE_DIR}/split` | Split-PDF output. |
| `TEMP_DIR` | `${OUTPUT_BASE_DIR}/temp` | Temporary files. |
| `LOG_DIR` | `${BASE_DIR}/logs` | Run logs. |

`docker-compose.yml` mounts:

```text
./data:/app/data
```

## MinerU API

Hard-coded in `config/settings.py`:

| Setting | Value |
| --- | --- |
| `UPLOAD_URL` | `https://mineru.net/api/v4/file-urls/batch` |
| `POLL_URL` | `https://mineru.net/api/v4/extract-results/batch/` |

## Official Quota Settings

| Variable | Default | Meaning |
| --- | ---: | --- |
| `MINERU_DAILY_FILE_LIMIT` | `5000` | Daily submitted file cap. |
| `MINERU_MAX_FILE_PAGES` | `200` | Max pages per uploaded PDF. |
| `MINERU_HIGH_PRIORITY_DAILY_PAGE_LIMIT` | `1000` | Local high-priority page accounting. |
| `MINERU_SUBMIT_FILE_RATE_PER_MINUTE` | `50` | Local submission token rate. |

## Worker And Batch Settings

Defined in `config/settings.py`:

| Setting | Current | Meaning |
| --- | ---: | --- |
| `MAX_WORKERS` | `12` | Worker thread count. |
| `FETCH_LIMIT` | `200` | Rows fetched per scheduler loop. |
| `BATCH_SIZE` | `50` | Handler batch size. |
| `WATCHDOG_INTERVAL` | `60` | Watchdog interval. |

Scheduler also has `MAX_DISPATCH_PER_ROUND = 100`.

## Per-Status Limits

| Status | Setting | Current |
| --- | --- | ---: |
| `FAILED` | `FAILED` | `5` |
| `SPLIT_NEEDED` | `SPLIT_NEEDED` | `5` |
| `DOWNLOADING` | `DOWNLOADING` | `20` |
| `PUT_DONE` | `POLL_CONCURRENCY` | `20` |
| `UPLOADED` | `PUT_CONCURRENCY` | `30` |
| `INIT` | `UPLOAD_CONCURRENCY` | `50` |

## QPS Settings

| Setting | Current | Used By |
| --- | ---: | --- |
| `QPS` | `2.0` | Shared limiter for split/fail paths. |
| `QPS_UPLOAD` | `1.0` | Create upload batch. |
| `QPS_PUT` | `10.0` | PUT upload. |
| `QPS_POLL` | `15.0` | Poll API. |
| `QPS_DOWNLOAD` | `5.0` | Result download. |

`RateLimiter.adjust()` can tune QPS based on recent failure rate.

## Retry And Scan

| Setting | Current | Meaning |
| --- | ---: | --- |
| `MAX_RETRY` | `5` | Max retry count. |
| `SCAN_INTERVAL` | `60` | Seconds between scans. |
| `SCAN_MAX_FILES` | `200000` | Max scanned files per pass. |
| `SCAN_BATCH_SLEEP` | `0.01` | Pause every 200 scanned files. |

## State Machine

`SCHEDULER_PRIORITY` controls processing order.

`VALID_TRANSITIONS` controls legal status updates. `update_tasks()` logs and skips invalid transitions.

When adding a status, update:

- `VALID_TRANSITIONS`
- `SCHEDULER_PRIORITY`
- `core/dispatcher.py`
- `core/scheduler.py`
- `docs/FLOW.md`
