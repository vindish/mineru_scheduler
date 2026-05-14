import random


def exponential_backoff(retry_count, base=2, max_delay=300, min_delay=10):
    """
    指数退避 + 抖动。
    retry_count=0 时至少 min_delay 秒，避免“失败 1 秒后立刻再试”。
    """
    delay = base ** retry_count
    jitter = random.uniform(0.5, 1.5)
    return min(max(min_delay, delay * jitter), max_delay)
