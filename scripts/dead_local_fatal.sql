-- 立刻把因本地写盘错误（路径过长/权限/磁盘满等）反复重试的旧任务拉到 DEAD，
-- 防止它们继续浪费 MinerU 每日配额。
UPDATE tasks
SET status = 'DEAD',
    error_type = COALESCE(error_type, 'LOCAL_FATAL'),
    dead_at = EXTRACT(EPOCH FROM now()),
    locked = 0,
    locked_at = NULL,
    updated_at = EXTRACT(EPOCH FROM now())
WHERE status IN ('FAILED', 'INIT', 'DOWNLOADING')
  AND (
       lower(coalesce(last_error, '')) LIKE '%errno 36%'
    OR lower(coalesce(last_error, '')) LIKE '%file name too long%'
    OR lower(coalesce(last_error, '')) LIKE '%errno 28%'
    OR lower(coalesce(last_error, '')) LIKE '%no space left%'
    OR lower(coalesce(last_error, '')) LIKE '%errno 13%'
    OR lower(coalesce(last_error, '')) LIKE '%permission denied%'
    OR lower(coalesce(last_error, '')) LIKE '%errno 30%'
    OR lower(coalesce(last_error, '')) LIKE '%read-only file system%'
  );
