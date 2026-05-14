import email.utils
import time
from pathlib import Path

import requests

from config.settings import TOKEN, UPLOAD_URL, POLL_URL
from utils.decorators import with_rate_limit
from utils.logger import logger


BASE_URL = "https://mineru.net/api/v4"


class RateLimitError(RuntimeError):
    """API 返回 429。retry_after 单位秒，可能为 0。"""

    def __init__(self, message, retry_after=0):
        super().__init__(message)
        self.retry_after = float(retry_after or 0)


def _parse_retry_after(header_value, default_seconds):
    """RFC7231: 数字（秒）或 HTTP-date。失败时回退 default_seconds。"""
    if not header_value:
        return default_seconds
    s = str(header_value).strip()
    try:
        return max(0.0, float(s))
    except (TypeError, ValueError):
        pass
    try:
        dt = email.utils.parsedate_to_datetime(s)
        if dt is not None:
            return max(0.0, dt.timestamp() - time.time())
    except (TypeError, ValueError):
        pass
    return default_seconds


class MineruClient:

    # 429 默认冷却（无 Retry-After 头时使用）
    DEFAULT_429_COOLDOWN = 30.0

    def __init__(self, timeout=30, rate_limiter=None):
        self.headers = {
            "Authorization": f"Bearer {TOKEN}",
        }
        self.timeout = timeout
        self.rate_limiter = rate_limiter

    # =========================
    # 🔧 通用请求封装
    # =========================
    def _request(self, method, url, **kwargs):
        timeout = kwargs.pop("timeout", self.timeout)
        headers = kwargs.pop("headers", None)

        # OSS 上传不带默认 headers
        if headers is None and "oss-" not in url:
            headers = self.headers

        try:
            resp = requests.request(
                method,
                url,
                headers=headers,
                timeout=timeout,
                **kwargs,
            )
        except requests.RequestException as e:
            raise RuntimeError(f"{method} {url} failed: {e}") from e

        # 429 单独处理：冷却 + 降速
        if resp.status_code == 429:
            retry_after = _parse_retry_after(
                resp.headers.get("Retry-After"),
                default_seconds=self.DEFAULT_429_COOLDOWN,
            )
            if self.rate_limiter:
                self.rate_limiter.cool_down(retry_after)
                # 同时把 QPS 折半（最低 0.2），避免 cooldown 结束后又冲爆
                try:
                    self.rate_limiter._set_qps(self.rate_limiter.qps * 0.5)
                except Exception:
                    pass
            raise RateLimitError(
                f"{method} {url} 429 Too Many Requests; cool_down={retry_after:.1f}s",
                retry_after=retry_after,
            )

        try:
            resp.raise_for_status()
        except requests.HTTPError as e:
            raise RuntimeError(f"{method} {url} failed: {e}") from e

        if kwargs.get("stream"):
            return resp

        if "application/json" in resp.headers.get("Content-Type", ""):
            data = resp.json()
            if data.get("code") != 0:
                raise RuntimeError(data.get("msg"))
            return data

        return resp

    # =========================
    # 🚀 1. 创建上传批次
    # =========================
    @with_rate_limit
    def create_upload_batch(self, files):
        return self._request(
            "POST",
            UPLOAD_URL,
            json={"files": files, "model_version": "vlm"},
        )

    # =========================
    # 📤 2. 上传文件（PUT 到 OSS）
    # =========================
    @with_rate_limit
    def upload_file(self, url, file_path):
        # OSS 也限 QPS 防止把上行带宽打满
        if self.rate_limiter:
            self.rate_limiter.acquire()

        try:
            with open(file_path, "rb") as f:
                resp = requests.put(url, data=f, timeout=self.timeout)
        except requests.RequestException as e:
            if self.rate_limiter:
                self.rate_limiter.record_fail()
            raise RuntimeError(f"PUT {url} failed: {e}") from e

        if resp.status_code in (200, 201):
            if self.rate_limiter:
                self.rate_limiter.record_success()
            return True

        if self.rate_limiter:
            self.rate_limiter.record_fail()

        if resp.status_code == 429:
            retry_after = _parse_retry_after(
                resp.headers.get("Retry-After"),
                default_seconds=self.DEFAULT_429_COOLDOWN,
            )
            if self.rate_limiter:
                self.rate_limiter.cool_down(retry_after)
            raise RateLimitError(
                f"PUT {url} 429; cool_down={retry_after:.1f}s",
                retry_after=retry_after,
            )

        raise RuntimeError(f"PUT {url} failed: {resp.status_code} {resp.text[:200]}")

    # =========================
    # 🔍 3. 轮询批次
    # =========================
    @with_rate_limit
    def poll_batch(self, batch_id):
        url = POLL_URL + f"{batch_id}"
        return self._request("GET", url, params={"batch_id": batch_id})

    # =========================
    # 📥 4. 下载文件
    # =========================
    @with_rate_limit
    def download_stream(self, url):
        if not url:
            raise ValueError("download url empty")
        return self._request("GET", url, stream=True)

    # =========================
    # 🔁 5. 简单重试封装
    # =========================
    def retry(self, func, retries=3, delay=2, *args, **kwargs):
        last_exc = None
        for i in range(retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_exc = e
                if i == retries - 1:
                    raise
                time.sleep(delay)
        if last_exc:
            raise last_exc

    # =========================
    # 🧪 6. 批次解析工具
    # =========================
    def parse_poll_result(self, extract_list, file_name):
        for item in extract_list:
            if item.get("file_name") == file_name:
                return item
        return None
