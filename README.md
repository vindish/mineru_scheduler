# MinerU Scheduler

MinerU Scheduler 是一个 Docker 化的 MinerU 批量 PDF 解析调度器。它扫描本地 PDF，写入 PostgreSQL 任务表，按状态机调度任务，调用 MinerU API 创建上传批次、PUT 上传文件、轮询解析结果、下载结果 ZIP，并对失败任务做重试、拆分和死信归档。

本版本已移除 SQLite 依赖，数据库改为 PostgreSQL，避免 NAS 文件锁、WAL、网络文件系统一致性导致的 SQLite 报错。

cd ~/mineru_scheduler
git pull   # 或者用你同步代码的方式

docker compose down
docker compose build --no-cache scheduler
docker compose up -d --force-recreate scheduler

# 启动自检几毫秒就过（不再递归数 PDF）
docker compose logs scheduler --tail 60 | grep -E '📥|来源目录|sample|✅ 配置检查'

# 紧接着应该能看到扫描进度，每 500 个 flush 一次
docker compose logs -f scheduler | grep -E 'SCAN|MONITOR'
docker compose logs -f scheduler | grep -E 'ERROR|429|warning|FAILED'

让端口生效得 up -d 一次（端口绑定属于容器创建时的属性，不重建不会出现）：

cd ~/mineru_scheduler
docker compose up -d --force-recreate postgres
docker compose ps   # 应该看到 0.0.0.0->/127.0.0.1->5432/tcp
验证一下能不能从宿主机连：

# 方式 1：psql（如果装了）
psql -h 127.0.0.1 -p 5432 -U mineru -d mineru_scheduler -c "select count(*) from tasks;"

# 方式 2：用容器里的 psql 临时连一下
docker run --rm -it --network host postgres:16-alpine \
  psql -h 127.0.0.1 -p 5432 -U mineru -d mineru_scheduler

# 方式 3：直接在 scheduler 容器里 ping 数据库
docker compose exec scheduler python -c "from db.repository import get_conn; c=get_conn().cursor(); c.execute('select count(*) from tasks'); print(c.fetchone())"
几点要点：

默认 127.0.0.1:5432:5432 是“最安全的暴露方式”——宿主机本地工具能连，外部连不上；
想从公司其他机器连：.env 里改成 POSTGRES_BIND=0.0.0.0，配合防火墙规则只放行可信 IP；
端口冲突（已经有 PostgreSQL 在跑）：POSTGRES_HOST_PORT=15432 改宿主机端口，容器内仍是 5432，不影响应用配置；
scheduler 服务本身没有 HTTP/RPC 端口，所以不需要暴露。如果你以后给它加上一个 metrics/health 端口（例如 prometheus_client 起 :9090），照同样的写法在 scheduler: 下加一个 ports: 段就行。

## 当前目标

在本地可恢复、可观测、可限速的前提下，尽量贴近 MinerU 官方频控上限运行：

- 单日提交上限：`5000` 份。
- 单文件页数上限：`200` 页。
- 高优每日额度：`1000` 页。
- 提交频控：本地按 `50` 文件/分钟 token bucket 控制。

## AI 快速入口

- 接手指南：[docs/AI_HANDOFF.md](docs/AI_HANDOFF.md)
- 文件地图：[docs/AI_FILE_MAP.md](docs/AI_FILE_MAP.md)
- 架构说明：[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- 任务流程：[docs/FLOW.md](docs/FLOW.md)
- 配置说明：[docs/CONFIG.md](docs/CONFIG.md)
- 数据库说明：[docs/DATABASE.md](docs/DATABASE.md)
- 运维手册：[docs/OPERATIONS.md](docs/OPERATIONS.md)

## 核心能力

- 自动扫描配置目录下的 PDF 文件，并写入 `tasks` 表。
- 使用 PostgreSQL 保存任务、锁、重试次数、错误、页数和 MinerU 返回信息。
- 使用 `Scheduler -> Dispatcher -> Handler` 分层调度。
- 每个处理阶段有独立 QPS 限速器：创建上传批次、PUT 上传、轮询、下载。
- 本地持久化 MinerU 每日额度，防止超过 `5000` 文件/天。
- 本地按分钟 token bucket 控制提交速度，目标贴近 `50` 文件/分钟。
- 上传前读取 PDF 页数，超过 `200` 页自动进入拆分流程。
- 失败任务可指数退避重试；不可恢复任务进入 `DEAD`。
- Watchdog 自动释放超时锁，降低异常退出后任务卡死概率。
- Docker Compose 一键启动应用和 PostgreSQL。

## 快速启动

1. 准备 `.env`：

```bash
cp .env.example .env
```

编辑 `.env`，填入：

```text
MINERU_TOKEN=你的 MinerU Token
POSTGRES_PASSWORD=强密码
```

2. 准备 PDF 目录：

```bash
mkdir -p data/pdf
```

把待处理 PDF 放入：

```text
data/pdf/
```

3. 启动 Docker 应用：

```bash
docker compose up -d --build
```

4. 查看日志：

```bash
docker compose logs -f scheduler
```

5. 停止：

```bash
docker compose down
```

PostgreSQL 数据保存在 Docker volume `postgres_data`，PDF、拆分文件、下载结果和日志通过 `./data:/app/data` 挂载到宿主机。

## 服务组成

```text
docker-compose.yml
  ├─ postgres   PostgreSQL 16
  └─ scheduler  Python 调度器
```

容器内默认路径：

```text
/app/data/
├── pdf/          # 输入 PDF
├── split/        # 拆分后的 PDF
├── download/     # 下载的 ZIP 结果
├── output/       # 预留输出目录
├── temp/         # 临时文件
└── logs/         # 日志
```

## 当前处理链路

```text
扫描 PDF
  -> tasks.status = INIT
  -> 调度器读取页数和额度
  -> 创建 MinerU 上传批次
  -> UPLOADED
  -> PUT 上传 PDF 到 upload_url
  -> PUT_DONE
  -> 轮询 MinerU batch 结果
  -> DOWNLOADING
  -> 下载 full_zip_url
  -> DOWNLOADED
```

失败分支：

```text
任意阶段失败
  -> FAILED
  -> FailHandler
     -> 可重试错误：INIT + next_run_time 延后
     -> 超页/超限：SPLIT_NEEDED
     -> 致命文件错误：DEAD
```

超页拆分分支：

```text
INIT 读取 page_count > MAX_FILE_PAGES
  -> SPLIT_NEEDED
  -> SplitHandler 拆成 <= 200 页子 PDF
  -> 原任务 SPLIT_DONE
  -> 子任务 INIT
```

## 项目结构

```text
.
├── Dockerfile
├── docker-compose.yml
├── main.py
├── config/
│   └── settings.py            # API、路径、PostgreSQL、频控、并发、状态机
├── core/
│   ├── scheduler.py           # 主调度循环
│   ├── dispatcher.py          # status -> handler
│   ├── quota_manager.py       # MinerU 本地额度管理
│   ├── worker_pool.py         # 线程池和背压
│   ├── rate_limiter.py        # 阶段级 QPS
│   └── watchdog.py            # 超时锁修复
├── db/
│   ├── repository.py          # PostgreSQL 连接、建表、锁、更新、插入
│   ├── task_row.py            # TaskRow 对象封装
│   └── migrations.sql         # PostgreSQL schema 参考
├── handlers/
│   ├── upload_handler.py
│   ├── put_handler.py
│   ├── poll_handler.py
│   ├── download_handler.py
│   ├── fail_handler.py
│   ├── retry_handler.py
│   └── split_handler.py
├── services/
│   ├── mineru_client.py
│   ├── storage.py
│   ├── pdf_splitter.py
│   └── file_watcher.py
├── scripts/
│   ├── scan_tasks.py
│   ├── repair_tasks.py
│   ├── reset_tasks.sql
│   └── retry_failed.sql
├── utils/
└── docs/
```

## 关键配置

配置来自 `.env`、环境变量和 [config/settings.py](config/settings.py)。

PostgreSQL：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `POSTGRES_HOST` | `postgres` | Docker Compose 内服务名 |
| `POSTGRES_PORT` | `5432` | PostgreSQL 端口 |
| `POSTGRES_DB` | `mineru_scheduler` | 数据库名 |
| `POSTGRES_USER` | `mineru` | 用户名 |
| `POSTGRES_PASSWORD` | `mineru_password` | 密码，生产环境必须修改 |
| `DATABASE_URL` | 空 | 如果设置，优先使用完整连接串 |

路径：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `BASE_DIR` | `/app/data` | 容器内运行数据根目录 |
| `SCAN_DIRS` | `/app/data/pdf` | 逗号分隔的扫描目录 |

官方频控：

| 变量 | 默认值 |
| --- | ---: |
| `MINERU_DAILY_FILE_LIMIT` | `5000` |
| `MINERU_MAX_FILE_PAGES` | `200` |
| `MINERU_HIGH_PRIORITY_DAILY_PAGE_LIMIT` | `1000` |
| `MINERU_SUBMIT_FILE_RATE_PER_MINUTE` | `50` |

## 数据库表

- `tasks`：任务状态、路径、锁、重试、错误、页数、MinerU batch/url。
- `api_quota_usage`：每日文件额度和高优页额度账本。

启动时 `main.py` 调用 `init_db()` 和 `ensure_schema()` 自动建表和补字段。

详见 [docs/DATABASE.md](docs/DATABASE.md)。

## 常用命令

查看任务状态：

```bash
docker compose exec postgres psql -U mineru -d mineru_scheduler \
  -c "SELECT status, COUNT(*) FROM tasks GROUP BY status ORDER BY COUNT(*) DESC;"
```

查看今日额度：

```bash
docker compose exec postgres psql -U mineru -d mineru_scheduler \
  -c "SELECT * FROM api_quota_usage ORDER BY quota_date DESC LIMIT 5;"
```

重新构建应用：

```bash
docker compose up -d --build scheduler
```

本地语法检查：

```bash
python3 -m compileall core handlers db services scripts config utils main.py
```

## 开发注意事项

- 不再使用 SQLite；不要再新增 `.db` 文件、`sqlite3`、`?` SQL placeholder 或 `INSERT OR IGNORE`。
- PostgreSQL 参数占位符使用 `%s`。
- 批量任务锁使用 `UPDATE ... WHERE id = ANY(%s) RETURNING id`。
- `update_tasks()` 只接受 `TaskRow`，并强校验状态迁移。
- Handler 处理完成后必须调用 `update_tasks()`，否则任务锁不会释放。
- 修改 MinerU 提交流程时必须处理 quota 的预留、提交、释放三段式。
- 新增任务字段时同步更新 `db/repository.py:init_db()`、`ensure_schema()`、`db/migrations.sql` 和 `docs/DATABASE.md`。

## 当前边界

- 调度器仍是单应用实例设计。PostgreSQL 已解决 NAS 上 SQLite 文件锁问题，但多实例同时跑还需要重新审视本地内存 quota token bucket。
- 分钟 token bucket 是进程内状态，应用重启会恢复满桶；每日 quota 持久化在 PostgreSQL。
- 高优额度目前是本地账本，没有向 MinerU API 发送未知高优参数。
