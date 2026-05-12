# MinerU Scheduler

MinerU Scheduler 是一个面向批量 PDF 解析任务的本地调度系统。它负责扫描本地 PDF 文件，调用 MinerU 接口创建上传任务，上传文件，轮询解析结果，下载结果压缩包，并对失败任务进行重试、拆分或归档处理。

项目当前使用 Python + SQLite 实现，适合单机批量处理场景。代码按调度、处理器、服务封装、数据库访问和工具层拆分，核心目标是让大量 PDF 文件可以稳定、限速、可恢复地流转完成。

## 核心能力

- 自动扫描 `data/pdf` 下的 PDF 文件并写入任务表。
- 基于任务状态进行优先级调度。
- 支持上传、PUT 上传、轮询、下载、失败重试、PDF 拆分等完整链路。
- 使用线程池执行任务，支持不同阶段的 QPS 限速。
- 使用 SQLite WAL 模式保存任务状态。
- 使用任务锁避免重复调度。
- Watchdog 自动释放超时锁，减少异常退出后的任务卡死。
- 支持失败任务指数退避重试。
- 对超限 PDF 支持拆分后重新进入处理流程。
- 对不可恢复任务写入 DEAD 状态。
- 日志同时输出到控制台和 `data/logs`。

## 处理流程

```text
扫描 PDF
  ↓
INIT
  ↓ 创建 MinerU 上传批次
UPLOADED
  ↓ PUT 文件到 upload_url
PUT_DONE
  ↓ 轮询 MinerU 解析结果
DOWNLOADING
  ↓ 下载 full_zip_url
DOWNLOADED
```

失败分支：

```text
任意处理阶段
  ↓
FAILED
  ├─ 可重试错误      → INIT
  ├─ 文件过大/超限   → SPLIT_NEEDED → SPLIT_DONE + 子任务 INIT
  └─ 致命错误        → DEAD
```

## 任务状态说明

| 状态 | 含义 |
| --- | --- |
| `INIT` | 初始任务，等待创建上传批次 |
| `UPLOADED` | 已获取 MinerU 上传 URL，等待 PUT 上传文件 |
| `PUT_DONE` | 文件已上传，等待轮询解析结果 |
| `DOWNLOADING` | MinerU 已解析完成，等待下载结果 ZIP |
| `DOWNLOADED` | 结果已下载完成 |
| `FAILED` | 当前处理失败，等待失败处理器分流 |
| `SPLIT_NEEDED` | 文件需要拆分 |
| `SPLIT_DONE` | 原始文件拆分完成，子任务已生成 |
| `DEAD` | 不再处理的死信任务 |

状态流转由 `config/settings.py` 中的 `VALID_TRANSITIONS` 控制，数据库更新时会校验非法状态迁移。

## 项目结构

```text
.
├── main.py                    # 程序入口，启动自检、扫描线程、监控线程、调度器
├── config/
│   └── settings.py            # 全局配置、QPS、并发、状态机、建表 SQL
├── core/
│   ├── scheduler.py           # 主调度循环，拉取任务、加锁、按状态分发
│   ├── dispatcher.py          # 根据状态选择对应 Handler
│   ├── worker_pool.py         # 线程池封装
│   ├── rate_limiter.py        # 简单 QPS 限速与自适应调整
│   └── watchdog.py            # 锁修复和运行监控
├── handlers/
│   ├── upload_handler.py      # 创建 MinerU 上传批次
│   ├── put_handler.py         # PUT 上传 PDF 文件
│   ├── poll_handler.py        # 轮询解析结果
│   ├── download_handler.py    # 下载结果 ZIP
│   ├── fail_handler.py        # 失败分流
│   ├── retry_handler.py       # 重试与退避
│   └── split_handler.py       # PDF 拆分并生成子任务
├── services/
│   ├── mineru_client.py       # MinerU HTTP API 封装
│   ├── storage.py             # 本地目录和文件路径管理
│   ├── pdf_splitter.py        # PDF 拆分逻辑
│   └── file_watcher.py        # 文件监听扩展入口
├── db/
│   ├── repository.py          # SQLite 连接、查询、加锁、更新、迁移
│   ├── task_row.py            # 任务行对象封装
│   ├── migrations.sql         # 建表/索引 SQL 参考
│   └── update_buffer.py       # 更新缓冲层雏形
├── task_queue/
│   ├── dlq.py                 # 死信队列处理
│   └── priority_queue.py      # 优先级排序工具
├── scripts/
│   ├── scan_tasks.py          # 扫描 PDF 并插入任务
│   ├── repair_tasks.py        # 修复 DEAD 任务脚本
│   ├── reset_tasks.sql        # 重置任务 SQL
│   └── retry_failed.sql       # 重试失败任务 SQL
└── utils/
    ├── logger.py              # 日志配置
    ├── startup_check.py       # 启动自检
    ├── backoff.py             # 指数退避
    ├── decorators.py          # 限速装饰器
    └── time_utils.py          # 时间工具
```

## 运行环境

建议使用 Python 3.10 或更高版本。

代码中使用到的第三方库包括：

- `requests`
- `PyPDF2` 或项目当前 `pdf_splitter.py` 所依赖的 PDF 库
- `watchdog`，仅文件监听扩展需要

如果项目还没有依赖文件，建议后续补充 `requirements.txt`。

## 快速开始

1. 创建数据目录并放入 PDF：

```bash
mkdir -p data/pdf
```

将待处理 PDF 放入：

```text
data/pdf/
```

2. 配置 MinerU Token：

```bash
export MINERU_TOKEN="你的 MinerU Token"
```

Windows PowerShell：

```powershell
$env:MINERU_TOKEN="你的 MinerU Token"
```

3. 启动：

```bash
python3 main.py
```

Windows 也可以使用：

```bat
run.bat
```

启动后程序会：

- 执行启动自检。
- 初始化 `data/db/tasks1.db`。
- 定期扫描 `data/pdf`。
- 启动调度器处理任务。
- 定期输出任务总数、完成数、失败数。

## 目录约定

运行后会自动生成以下目录：

```text
data/
├── pdf/          # 输入 PDF
├── split/        # 拆分后的 PDF
├── download/     # 下载的结果 ZIP
├── output/       # 预留输出目录
├── temp/         # 临时文件
├── db/           # SQLite 数据库
└── logs/         # 运行日志
```

## 配置说明

主要配置位于 `config/settings.py`。

| 配置 | 说明 |
| --- | --- |
| `TOKEN` | 从环境变量 `MINERU_TOKEN` 读取 |
| `UPLOAD_URL` | MinerU 创建上传批次接口 |
| `POLL_URL` | MinerU 轮询接口前缀 |
| `BASE_DIR` | 数据根目录，默认 `data` |
| `DB_NAME` | SQLite 数据库文件名 |
| `SCAN_DIRS` | 扫描 PDF 的目录列表 |
| `MAX_WORKERS` | 线程池最大线程数 |
| `QPS_UPLOAD` | 创建上传批次限速 |
| `QPS_PUT` | PUT 上传限速 |
| `QPS_POLL` | 轮询限速 |
| `QPS_DOWNLOAD` | 下载限速 |
| `FETCH_LIMIT` | 调度器每轮最多拉取任务数 |
| `BATCH_SIZE` | 每批提交给 handler 的任务数 |
| `MAX_RETRY` | 最大重试次数 |
| `SCAN_INTERVAL` | 扫描间隔 |
| `SCHEDULER_PRIORITY` | 调度优先级 |
| `VALID_TRANSITIONS` | 状态机合法迁移规则 |

## 数据库表

核心表为 `tasks`。

重要字段：

| 字段 | 说明 |
| --- | --- |
| `id` | 任务 ID |
| `file_path` | PDF 文件路径，唯一索引 |
| `file_name` | 文件名 |
| `status` | 当前任务状态 |
| `api_task_id` | MinerU batch_id |
| `upload_url` | PUT 上传地址 |
| `zip_url` | 解析结果下载地址 |
| `retry_count` | 当前重试次数 |
| `max_retry` | 最大重试次数 |
| `next_run_time` | 下次允许运行时间 |
| `locked` | 是否被调度锁定 |
| `locked_at` | 锁定时间 |
| `last_error` | 最近错误 |
| `error_type` | 错误类型 |
| `parent_id` | 拆分子任务对应的父任务 ID |
| `dead_at` | 进入 DEAD 的时间 |
| `created_at` | 创建时间 |
| `updated_at` | 更新时间 |

启动时 `ensure_schema()` 会对旧库补充缺失字段和索引。

## 调度机制

`Scheduler` 每轮执行以下步骤：

1. 从数据库拉取可运行任务。
2. 使用 `lock_tasks()` 将任务标记为 `locked=1`。
3. 按 `SCHEDULER_PRIORITY` 分组。
4. 根据不同状态的并发配额截断任务数量。
5. 提交到 `WorkerPool`。
6. `Dispatcher` 根据状态调用对应 handler。
7. handler 成功或失败后调用 `update_tasks()` 写回状态，并释放锁。

如果 handler 抛出未捕获异常，`Dispatcher` 会记录异常并调用 `unlock_tasks()` 释放本批任务，避免任务永久卡住。

## 锁和恢复机制

任务锁字段：

```text
locked
locked_at
```

调度器只拉取 `locked=0` 的任务。任务被分发前会被锁住，处理完成后由 `update_tasks()` 解锁。

`Watchdog` 会周期性调用 `heal_locks()`：

- 释放超过超时时间的锁。
- 释放 `locked=1` 但 `locked_at IS NULL` 的异常锁。

这可以处理程序异常退出、worker 崩溃或未预期异常导致的任务卡死。

## 日志

日志配置在 `utils/logger.py`。

输出位置：

- 控制台
- `data/logs/run_YYYYMMDD_HHMMSS.log`

常见日志前缀：

| 前缀 | 含义 |
| --- | --- |
| `[SCAN]` | 扫描任务 |
| `[SCHEDULER]` | 调度器 |
| `[DISPATCH]` | 任务分发 |
| `[UPLOAD]` | 创建上传任务 |
| `[PUT FAIL]` | PUT 上传失败 |
| `[POLL]` | 轮询解析状态 |
| `[DOWNLOAD]` | 下载结果 |
| `[FAIL]` | 失败分流 |
| `[WATCHDOG]` | 锁恢复 |
| `[MONITOR]` | 任务统计 |

## 常用维护操作

查看任务统计：

```sql
SELECT status, COUNT(*) FROM tasks GROUP BY status;
```

重试失败任务：

```sql
UPDATE tasks
SET status='INIT',
    locked=0,
    locked_at=NULL,
    next_run_time=NULL
WHERE status='FAILED';
```

释放所有锁：

```sql
UPDATE tasks
SET locked=0,
    locked_at=NULL
WHERE locked=1;
```

查看死信任务：

```sql
SELECT id, file_name, last_error
FROM tasks
WHERE status='DEAD'
ORDER BY dead_at DESC;
```

## 当前限制

- 仍是单机 SQLite 架构，高并发和多进程部署能力有限。
- 状态流转还依赖 handler 手动设置 `t.status`，存在人为写错状态的风险。
- 任务更新是直接批量写库，尚未实现稳定的写缓冲和批量提交策略。
- 没有完善的单元测试和集成测试。
- 没有依赖锁定文件，例如 `requirements.txt`。
- 配置仍集中在 Python 文件中，不支持 `.env` 或 YAML/TOML 配置。
- MinerU API 错误类型分类还比较粗，需要更细的错误码策略。
- 文件监听能力存在扩展入口，但主流程当前以定时扫描为主。
- 缺少结构化指标暴露，例如 Prometheus metrics。

## 后续更新方向

### 1. 数据库升级

当前 SQLite 适合本地单机批处理。后续如果任务量继续增加，建议迁移到 PostgreSQL：

- 使用行级锁或 `SELECT ... FOR UPDATE SKIP LOCKED` 做并发任务领取。
- 支持多进程、多机器调度。
- 提升大任务量下的查询、索引和写入能力。
- 保留 SQLite 作为本地轻量模式。

### 2. 引入 Redis 分布式锁和队列

后续可以将调度改为 Redis + Pipeline Scheduler：

- Redis 负责短期任务队列和分布式锁。
- PostgreSQL 负责最终任务状态。
- Scheduler 只负责领取和投递任务。
- Worker 可以水平扩展。

目标架构：

```text
Scanner → PostgreSQL → Scheduler → Redis Queue → Worker Pool → MinerU API
                         ↑                         ↓
                       Watchdog ←────────────── Status Update
```

### 3. TaskRow 状态机升级

建议把状态迁移逻辑收敛到 `TaskRow`：

```python
t.transition("PUT_DONE")
t.mark_failed(error)
t.mark_dead(error_type="FATAL")
t.mark_retry(next_run_time)
t.mark_split_needed()
```

这样 handler 不再直接写：

```python
t.status = "FAILED"
```

收益：

- 减少非法状态迁移。
- 统一清理字段，例如失败时清理 URL 或成功时清理错误。
- 更容易测试状态机。
- 方便未来扩展状态审计日志。

### 4. 更新缓冲层

`db/update_buffer.py` 可以继续完善为稳定的 micro-batch 写入层：

- 多个 worker 只提交状态变更对象。
- 单独写线程批量 flush。
- 降低 SQLite 写锁竞争。
- 后续迁移 PostgreSQL 时也能复用批量更新模型。

### 5. 完善错误分类

当前 `FailHandler` 主要依赖错误文本判断。后续建议引入标准错误类型：

- `RATE_LIMIT`
- `FILE_MISSING`
- `INVALID_PDF`
- `PDF_TOO_LARGE`
- `NETWORK_TIMEOUT`
- `API_ERROR`
- `AUTH_ERROR`
- `UNKNOWN`

每个 handler 捕获异常后写入 `error_type`，失败处理器根据 `error_type` 分流。

### 6. 增加测试体系

建议补充：

- `TaskRow` 状态机测试。
- `repository` 状态迁移测试。
- `Scheduler` 加锁和解锁测试。
- `FailHandler` 错误分流测试。
- `MineruClient` HTTP mock 测试。
- PDF 拆分测试。

推荐使用：

```text
pytest
responses 或 requests-mock
temporary sqlite database
```

### 7. 配置和部署标准化

建议增加：

- `.env.example`
- `requirements.txt` 或 `pyproject.toml`
- Dockerfile
- docker-compose 示例
- 日志等级配置
- 不同环境的配置文件

### 8. 可观测性增强

后续可以增加：

- 任务状态统计接口。
- Prometheus metrics。
- 失败原因排行榜。
- 每个阶段耗时统计。
- QPS、失败率、队列长度监控。
- 简单 Web Dashboard。

### 9. 文件监听替代轮询扫描

当前主流程使用定时扫描。后续可以将 `services/file_watcher.py` 接入主程序：

- 新 PDF 创建后立即入库。
- 定时扫描作为兜底。
- 避免大目录频繁 `rglob` 带来的开销。

### 10. 更安全的结果管理

下载文件当前按 PDF stem 生成 ZIP 名称。后续建议：

- 使用任务 ID 作为结果目录。
- 保存 MinerU 返回的原始 JSON。
- 记录下载文件大小和 checksum。
- 对下载 ZIP 做完整性校验。
- 防止同名文件覆盖。

## 推荐近期开发顺序

1. 补 `requirements.txt` 和 `.env.example`。
2. 为 `TaskRow` 增加状态方法，收敛状态变更。
3. 给 `repository` 和 `FailHandler` 增加测试。
4. 完善错误类型枚举，减少字符串判断。
5. 接入 `UpdateBuffer` 做批量状态写入。
6. 增加 SQLite 到 PostgreSQL 的迁移方案。
7. 增加基础 Dashboard 或 metrics。

## 开发注意事项

- 不要绕过 `update_tasks()` 直接更新任务状态，除非是维护脚本。
- 新增状态时必须同步更新 `VALID_TRANSITIONS`。
- handler 内部应保证每个任务最终写回状态或被解锁。
- 外部 API 请求必须经过限速器，避免触发 429。
- 对可能长期运行的任务要设置合理超时。
- 对文件路径统一使用 `Storage`，避免散落路径拼接。
- 对批量任务保持幂等，重复执行不应破坏已有结果。

## 当前项目定位

这个项目目前处于可用的单机批处理调度器阶段。它已经具备完整业务链路、任务状态持久化、限速、重试和基础恢复能力。

下一阶段的重点不是继续堆 handler，而是提升工程可靠性：

- 状态机模型化。
- 数据库写入体系化。
- 错误类型标准化。
- 测试覆盖关键路径。
- 为 PostgreSQL、Redis 和多 worker 架构做演进准备。
