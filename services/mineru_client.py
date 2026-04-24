import time
from pathlib import Path

import requests
from config.settings import TOKEN,UPLOAD_URL,POLL_URL
from utils.decorators import with_rate_limit


BASE_URL = "https://mineru.net/api/v4"


class MineruClient:

    def __init__(self, timeout=30, rate_limiter=None):
        self.headers = {
            # "Content-Type": "application/json",
            "Authorization": f"Bearer {TOKEN}"
        }
        self.timeout = timeout
        self.rate_limiter = rate_limiter
        # self.download_semaphore = Semaphore(3)

    # =========================
    # 🔧 通用请求封装（核心）
    # =========================
    def _request(self, method, url, **kwargs):
        try:

            # ✅ 如果外部传了 timeout，就用外部的（更灵活）
            timeout = kwargs.pop("timeout", self.timeout)
            headers = kwargs.pop("headers", None)

            # 🔥 如果是 OSS 上传，不带默认 headers
            if headers is None and "oss-" not in url:
                headers = self.headers

            resp = requests.request(
                method,
                url,
                headers=headers,
                timeout=timeout,
                **kwargs
            )

            if resp.status_code == 429:
                if self.rate_limiter:
                    self.rate_limiter.qps *= 0.5

            resp.raise_for_status()
            # 🔥 成功统计

            if kwargs.get("stream"):
                return resp   # 🔥 直接返回，不做 JSON解析
            # JSON解析
            if "application/json" in resp.headers.get("Content-Type", ""):
                data = resp.json()

                if data.get("code") != 0:
                    raise RuntimeError(data.get("msg"))

                return data

            return resp

        except Exception as e:
            # 🔥 失败统计

            raise RuntimeError(f"{method} {url} failed: {e}") from e

    # =========================
    # 🚀 1. 创建上传批次
    # =========================
    @with_rate_limit
    def create_upload_batch(self, files):
        """
        files:
        [
            {"name": "a.pdf", "data_id": "1"},
            {"name": "b.pdf", "data_id": "2"},
            ...
        ]
        """
        url = UPLOAD_URL

        data = self._request(
            "POST",
            url,
            json={
                "files": files,
                "model_version": "vlm"
            }
        )

        return data  # batch_id + file_urls

    # =========================
    # 📤 2. 上传文件（PUT）
    # =========================
    @with_rate_limit
    def upload_file(self, url, file_path):

        if self.rate_limiter:
            self.rate_limiter.acquire()   # ✅ 手动限速

        with open(file_path, "rb") as f:
            resp = requests.put(
                url,
                data=f,
                timeout=self.timeout
            )

        if self.rate_limiter:
            self.rate_limiter.record_success()

        if resp.status_code not in (200, 201):
            if self.rate_limiter:
                self.rate_limiter.record_fail()

            raise RuntimeError(
                f"upload failed: {resp.status_code} {resp.text[:200]}"
            )

        return True

    # =========================
    # 🔍 3. 轮询批次
    # =========================
    @with_rate_limit
    def poll_batch(self, batch_id):
        url = POLL_URL + f"{batch_id}"

        data = self._request(
            "GET",
            url,
            params={"batch_id": batch_id}
        )

        return data

    # =========================
    # 📥 4. 下载文件
    # =========================
    @with_rate_limit
    def download_stream(self, url):

        if not url:
            raise ValueError("download url empty")

        resp = self._request("GET",url, stream=True)


        return resp


    # =========================
    # 🔁 5. 简单重试封装
    # =========================
    def retry(self, func, retries=3, delay=2, *args, **kwargs):
        for i in range(retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                if i == retries - 1:
                    raise
                time.sleep(delay)

    # =========================
    # 🧪 6. 批次解析工具（辅助）
    # =========================
    def parse_poll_result(self, extract_list, file_name):
        """
        从 poll 返回中找到对应文件状态
        """
        for item in extract_list:
            if item.get("file_name") == file_name:
                return item
        return None