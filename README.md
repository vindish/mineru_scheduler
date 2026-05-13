# MinerU Scheduler

MinerU Scheduler 是一个面向 MinerU 批量 PDF 解析的本地调度系统。它扫描本地 PDF，写入 SQLite 任务表，按状态机调度任务，调用 MinerU API 创建上传批次、PUT 上传文件、轮询解析结果、下载结果 ZIP，并对失败任务做重试、拆分和死信归档。

当前版本重点适配官方频控策略：

- 单日提交上限：`5000` 份。
- 单文件页数上限：`200` 页。
- 高优每日额度：`1000` 页。
- 提交频控：按 `50` 文件/分钟的本地 token bucket 控制。

项目目标不是盲目加并发，而是在本地可恢复、可观测、可限速的前提下，尽量贴近官方频控上限跑满吞吐。

## 快速入口

- AI 接手先读：[docs/AI_HANDOFF.md](docs/AI_HANDOFF.md)
- 架构说明：[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- 任务流程：[docs/FLOW.md](docs/FLOW.md)
- 配置说明：[docs/CONFIG.md](docs/CONFIG.md)
- 数据库说明：[docs/DATABASE.md](docs/DATABASE.md)
- 运行维护：[docs/OPERATIONS.md](docs/OPERATIONS.md)

## 核心能力

- 自动扫描配置目录下的 PDF 文件，并以 `INIT` 状态写入任务表。
- 使用 SQLite WAL 模式保存任务、锁、重试次数、错误、页数和 MinerU 返回信息。
- 使用 `Scheduler -> Dispatcher -> Handler` 分层调度任务。
- 每个处理阶段有独立 QPS 限速器：创建上传批次、PUT 上传、轮询、下载。
- 本地持久化每日 MinerU 额度，防止超过 `5000` 文件/天。
- 本地按分钟 token bucket 控制提交速度，目标贴近 `50` 文件/分钟。
- 上传前读取 PDF 页数，超过 `200` 页自动进入拆分流程。
- 失败任务可指数退避重试；不可恢复任务进入 `DEAD`。
- Watchdog 自动释放超时锁，降低异常退出后任务卡死概率。
- 日志输出到控制台和 `data/logs`。

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
  -> SplitHandler 使用 PDFSplitter 拆成 <= 200 页子 PDF
  -> 原任务 SPLIT_DONE
  -> 子任务 INIT
```

## 项目结构

```text
.
├── main.py                    # 入口：自检、建表、扫描线程、监控线程、调度器
├── config/
│   └── settings.py            # API、路径、官方频控、并发、状态机、建表 SQL
├── core/
│   ├── scheduler.py           # 主调度循环：拉取、加锁、分组、额度预留、投递
│   ├── dispatcher.py          # 根据 status 调用对应 Handler
│   ├── quota_manager.py       # MinerU 本地额度管理：日额度 + 分钟 token bucket
│   ├── worker_pool.py         # ThreadPoolExecutor + 信号量背压
│   ├── rate_limiter.py        # 阶段级 QPS 限速与简单自适应
│   └── watchdog.py            # 周期释放超时锁
├── handlers/
│   ├── upload_handler.py      # 创建 MinerU 上传批次，成功后提交额度
│   ├── put_handler.py         # PUT 上传 PDF 文件
│   ├── poll_handler.py        # 轮询 MinerU 解析状态
│   ├── download_handler.py    # 下载解析结果 ZIP
│   ├── fail_handler.py        # 失败分流
│   ├── retry_handler.py       # 指数退避重试
│   └── split_handler.py       # 拆分超页 PDF 并生成子任务
├── services/
│   ├── mineru_client.py       # MinerU HTTP API 封装
│   ├── storage.py             # 数据目录、DB 路径、下载路径、拆分路径
│   ├── pdf_splitter.py        # PyPDF2 拆分实现
│   └── file_watcher.py        # 文件监听扩展入口
├── db/
│   ├── repository.py          # SQLite 连接、迁移、查询、锁、更新、插入
│   ├── task_row.py            # TaskRow 对象封装
│   ├── migrations.sql         # 建表 SQL 参考
│   └── update_buffer.py       # 更新缓冲扩展入口
├── scripts/
│   ├── scan_tasks.py          # 扫描 PDF 并写入 INIT 任务
│   ├── repair_tasks.py        # 修复任务脚本
│   ├── reset_tasks.sql        # 重置任务 SQL
│   └── retry_failed.sql       # 重试失败任务 SQL
├── task_queue/
│   ├── dlq.py                 # DEAD 状态写入
│   └── priority_queue.py      # 优先级排序工具
├── utils/
│   ├── logger.py              # 日志
│   ├── startup_check.py       # 启动自检
│   ├── backoff.py             # 指数退避
│   ├── decorators.py          # 限速装饰器
│   └── time_utils.py          # 时间工具
└── docs/                      # 面向人和 AI 的项目说明
```

## 运行环境

建议 Python 3.10+。

依赖见 [requirements.txt](requirements.txt)：

```bash
pip install -r requirements.txt
```

需要设置 MinerU Token：

```bash
export MINERU_TOKEN="你的 MinerU Token"
```

Windows PowerShell：

```powershell
$env:MINERU_TOKEN="你的 MinerU Token"
```

## 启动

```bash
python3 main.py
```

Windows 可使用：

```bat
run.bat
```

启动后会执行：

1. `run_checks()` 启动自检。
2. 初始化 SQLite 表和索引。
3. `ensure_schema()` 迁移旧库字段。
4. 后台启动 `scan_loop()`，周期扫描 PDF。
5. 后台启动 `monitor_loop()`，周期输出任务总数、完成数、失败数。
6. 启动 `Scheduler.run()` 主循环。

## 目录约定

路径由 `services/storage.py` 和 `config/settings.py` 决定。当前默认 `BASE_DIR` 是项目作者本机 NAS 路径：

```text
/mnt/nas/downloadBT/code_Project/quiz_taskrow_system/scheduler_system/data
```

如果迁移机器，优先修改：

- `BASE_DIR`
- `SCAN_DIRS`
- `DB_NAME`

运行时数据目录结构：

```text
data/
├── pdf/          # 输入 PDF
├── split/        # 拆分后的 PDF
├── download/     # 下载的 ZIP 结果
├── output/       # 预留输出目录
├── temp/         # 临时文件
├── db/           # SQLite 数据库
└── logs/         # 日志
```

## 关键配置

主要配置在 [config/settings.py](config/settings.py)。

官方频控：

| 配置 | 默认值 | 含义 |
| --- | ---: | --- |
| `DAILY_FILE_LIMIT` | `5000` | 每自然日最多提交文件数 |
| `MAX_FILE_PAGES` | `200` | 单文件最大页数 |
| `HIGH_PRIORITY_DAILY_PAGE_LIMIT` | `1000` | 高优每日页额度 |
| `SUBMIT_FILE_RATE_PER_MINUTE` | `50` | 本地提交 token bucket 速率 |

吞吐相关：

| 配置 | 当前值 | 含义 |
| --- | ---: | --- |
| `MAX_WORKERS` | `12` | 线程池最大线程数 |
| `FETCH_LIMIT` | `200` | 调度器每轮最多拉取任务数 |
| `BATCH_SIZE` | `50` | Handler 批大小 |
| `UPLOAD_CONCURRENCY` | `50` | INIT 阶段每轮最多投递 |
| `PUT_CONCURRENCY` | `30` | UPLOADED 阶段每轮最多投递 |
| `POLL_CONCURRENCY` | `20` | PUT_DONE 阶段每轮最多投递 |
| `DOWNLOADING` | `20` | DOWNLOADING 阶段每轮最多投递 |

QPS：

| 配置 | 当前值 | 对应阶段 |
| --- | ---: | --- |
| `QPS_UPLOAD` | `1.0` | 创建上传批次 |
| `QPS_PUT` | `10.0` | PUT 上传文件 |
| `QPS_POLL` | `15.0` | 轮询解析结果 |
| `QPS_DOWNLOAD` | `5.0` | 下载结果 |

## 数据库

核心业务表：

- `tasks`：任务状态、文件路径、锁、重试、错误、页数、MinerU batch/url 信息。
- `api_quota_usage`：每日 MinerU 提交额度和高优页额度使用量。

`tasks.status` 是系统的主状态机。合法流转由 `VALID_TRANSITIONS` 控制，`update_tasks()` 会拒绝非法状态迁移。

详见 [docs/DATABASE.md](docs/DATABASE.md)。

## 额度策略

额度策略由 [core/quota_manager.py](core/quota_manager.py) 管理：

- 每次调度 `INIT` 前，先读取 PDF 页数。
- 页数超过 `MAX_FILE_PAGES` 的任务直接转 `SPLIT_NEEDED`。
- 页数合格后调用 `reserve_submission_batch()` 预留文件额度。
- 若日额度不足，任务延后到次日。
- 若分钟 token 不足，任务按 token 恢复时间延后。
- `UploadHandler` 创建上传批次成功后调用 `commit_reservations()`。
- 上传前本地校验失败或 API 调用失败时调用 `release_reservations()`。

注意：当前代码没有向 MinerU API 写入未知的“高优”请求参数，只在本地记录高优页额度。若官方 API 后续提供明确参数，应在 `services/mineru_client.py:create_upload_batch()` 中补充，并同步更新文档。

## 常用命令

语法检查：

```bash
python3 -m compileall core handlers db services config utils main.py
```

查看改动：

```bash
git status --short
git diff --stat
git diff --check
```

直接查看数据库：

```bash
sqlite3 /path/to/tasks1.db
```

常用 SQL：

```sql
SELECT status, COUNT(*) FROM tasks GROUP BY status;
SELECT * FROM api_quota_usage ORDER BY quota_date DESC LIMIT 5;
SELECT id, status, file_name, last_error FROM tasks WHERE status='FAILED' LIMIT 20;
```

## 开发注意事项

- `update_tasks()` 只接受 `TaskRow`，并强校验状态迁移。
- Handler 处理完成后必须通过 `update_tasks()` 写回，否则锁不会释放。
- 调度器已经会释放未投递任务锁，不要在 Handler 内重复处理不属于本批的任务。
- 新增状态时必须同步更新 `VALID_TRANSITIONS`、调度优先级和文档。
- 修改 MinerU 提交流程时必须考虑 `ApiQuotaManager` 的预留、提交、释放三段式。
- SQLite 适合当前单机模型；如果要多进程或多机器调度，必须重做锁和 quota 的并发语义。

## 当前边界

- 项目是单机调度器，不是分布式队列。
- `api_quota_usage` 的分钟 token 是进程内状态，进程重启后分钟桶会恢复满，但日额度仍持久化。
- 高优额度目前是本地账本，没有官方高优 API 参数接入。
- `BASE_DIR` 和 `SCAN_DIRS` 当前写死为 NAS 路径，迁移环境时需要修改。
- `TODO.md` 中记录了一些历史想法，但当前项目事实以代码和 `docs/` 为准。
