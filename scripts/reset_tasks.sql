UPDATE tasks
SET status='INIT',
    retry_count=0,
    locked=0;