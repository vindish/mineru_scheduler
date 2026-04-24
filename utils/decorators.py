import functools


def with_rate_limit(func):
    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):

        limiter = getattr(self, "rate_limiter", None)

        if limiter:
            limiter.acquire()

        try:
            result = func(self, *args, **kwargs)

            if limiter:
                limiter.record_success()

            return result

        except Exception as e:
            if limiter:
                limiter.record_fail()

            # 🔥 保留原始异常链（关键）
            raise

    return wrapper