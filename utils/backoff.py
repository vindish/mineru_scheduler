import random


def exponential_backoff(retry_count, base=2, max_delay=300):
    delay = base ** retry_count
    jitter = random.uniform(0.5, 1.5)
    return min(delay * jitter, max_delay)