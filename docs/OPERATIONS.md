# Operations

This runbook assumes Docker Compose.

## First Run

```bash
cp .env.example .env
```

Edit `.env`:

```text
MINERU_TOKEN=your-token
POSTGRES_PASSWORD=strong-password
```

Prepare input directory:

```bash
mkdir -p data/pdf
```

Start:

```bash
docker compose up -d --build
```

Watch logs:

```bash
docker compose logs -f scheduler
```

## Stop And Restart

Stop containers:

```bash
docker compose down
```

Restart scheduler only:

```bash
docker compose restart scheduler
```

Rebuild scheduler:

```bash
docker compose up -d --build scheduler
```

Remove PostgreSQL data volume only when you intentionally want a clean DB:

```bash
docker compose down -v
```

## Health Checks

PostgreSQL:

```bash
docker compose ps
docker compose exec postgres pg_isready -U mineru -d mineru_scheduler
```

Scheduler logs:

```bash
docker compose logs --tail=200 scheduler
```

## Common Queries

Status counts:

```bash
docker compose exec postgres psql -U mineru -d mineru_scheduler \
  -c "SELECT status, COUNT(*) FROM tasks GROUP BY status ORDER BY COUNT(*) DESC;"
```

Today quota:

```bash
docker compose exec postgres psql -U mineru -d mineru_scheduler \
  -c "SELECT * FROM api_quota_usage ORDER BY quota_date DESC LIMIT 5;"
```

Locked tasks:

```bash
docker compose exec postgres psql -U mineru -d mineru_scheduler \
  -c "SELECT id, status, locked_at, file_name FROM tasks WHERE locked=1 ORDER BY locked_at;"
```

Future-delayed tasks:

```bash
docker compose exec postgres psql -U mineru -d mineru_scheduler \
  -c "SELECT id, status, to_timestamp(next_run_time), file_name FROM tasks WHERE next_run_time IS NOT NULL AND next_run_time > extract(epoch from now()) ORDER BY next_run_time LIMIT 50;"
```

Recent failures:

```bash
docker compose exec postgres psql -U mineru -d mineru_scheduler \
  -c "SELECT id, retry_count, file_name, left(last_error, 200) FROM tasks WHERE status='FAILED' ORDER BY updated_at DESC LIMIT 20;"
```

## Log Prefixes

| Prefix | Meaning |
| --- | --- |
| `[SCAN]` | Scan progress and insert count. |
| `[SCHEDULER]` | Fetch/lock and queue state. |
| `[DISPATCH]` | Handler dispatch. |
| `[HEARTBEAT]` | Queue, QPS, and quota state. |
| `[QUOTA]` | Quota commit/release/defer. |
| `[PAGE-CHECK]` | Page count routing. |
| `[UPLOAD]` | MinerU upload batch. |
| `[PUT FAIL]` | PUT upload failure. |
| `[POLL]` | Poll progress. |
| `[DOWNLOAD OK]` | ZIP downloaded. |
| `[DOWNLOAD FAIL]` | Download failed. |
| `[WATCHDOG]` | Lock recovery. |
| `[INVALID TRANSITION]` | State machine rejection. |

## Common Problems

### Scheduler Cannot Connect To DB

Check:

```bash
docker compose logs postgres
docker compose logs scheduler
docker compose exec postgres pg_isready -U mineru -d mineru_scheduler
```

Confirm `.env` password and compose environment match.

### No Tasks Are Inserted

Check:

- Is `./data/pdf` mounted?
- Are files ending in `.pdf`?
- Does scheduler log `[SCAN]`?

```bash
docker compose exec scheduler ls -la /app/data/pdf
```

### Tasks Are Locked

Watchdog releases locks older than 300 seconds.

Manual unlock after confirming no scheduler worker is active:

```bash
docker compose exec postgres psql -U mineru -d mineru_scheduler \
  -c "UPDATE tasks SET locked=0, locked_at=NULL WHERE locked=1;"
```

### Quota Exhausted

Check:

```bash
docker compose exec postgres psql -U mineru -d mineru_scheduler \
  -c "SELECT * FROM api_quota_usage ORDER BY quota_date DESC LIMIT 1;"
```

Expected:

- Daily quota exhaustion delays `INIT` tasks until next local day.
- Minute token exhaustion delays tasks briefly.

### PostgreSQL Data Reset

This deletes DB data:

```bash
docker compose down -v
```

It does not delete `./data/pdf`, `./data/download`, or `./data/split`.

## Development Checks

Compile:

```bash
python3 -m compileall core handlers db services scripts config utils main.py
```

Diff hygiene:

```bash
git diff --check
```

Build:

```bash
docker compose build scheduler
```

## Safe Manual Recovery

Retry failed tasks:

```bash
docker compose exec postgres psql -U mineru -d mineru_scheduler \
  -c "UPDATE tasks SET locked=0, locked_at=NULL, next_run_time=NULL WHERE status='FAILED';"
```

Reset one task:

```bash
docker compose exec postgres psql -U mineru -d mineru_scheduler \
  -c "UPDATE tasks SET status='INIT', locked=0, locked_at=NULL, next_run_time=NULL, retry_count=0, last_error=NULL WHERE id=123;"
```

Do not mass reset `DOWNLOADED` unless you intentionally want to reprocess completed files.
