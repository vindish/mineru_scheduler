UPDATE tasks
SET status='INIT',
    retry_count=retry_count+1,
    locked=0
WHERE status='FAILED';