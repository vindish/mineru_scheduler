from pathlib import Path
import hashlib
import re
import shutil

from config.settings import (
    BASE_DIR,
    PDF_INPUT_DIRS,
    OUTPUT_BASE_DIR,
    DOWNLOAD_DIR,
    OUTPUT_DIR,
    SPLIT_DIR,
    TEMP_DIR,
)


# 文件存储规范层
# 它负责统一管理“文件保存路径”和“文件是否存在”的逻辑
# 所有“PDF 来源”和“输出文件”都通过它统一访问；
# 这些路径来自 config.settings，禁止在其他模块再硬编码。


class Storage:
    """
    文件存储规范层（统一入口）
    """

    def __init__(self, base_dir=None):
        # 默认沿用 settings 中的统一根目录
        self.base_dir = Path(base_dir).resolve() if base_dir else BASE_DIR

        # 输出根（默认即 BASE_DIR，可被 OUTPUT_BASE_DIR 单独覆盖）
        self.output_base_dir = OUTPUT_BASE_DIR

        # 输入：PDF 来源目录列表（来自 settings）
        self.input_dirs = list(PDF_INPUT_DIRS)
        # 取第一个作为代表性 pdf_dir，主要用于启动自检
        self.pdf_dir = self.input_dirs[0] if self.input_dirs else (self.base_dir / "pdf")

        # 输出：下载、解析、临时、拆分（来自 settings，可独立覆盖）
        self.download_dir = DOWNLOAD_DIR
        self.output_dir = OUTPUT_DIR
        self.temp_dir = TEMP_DIR
        self.split_dir = SPLIT_DIR

        # 兜底确保“输出”目录存在（输入目录不能在这里创建，原因见 settings.py）
        for d in [self.download_dir, self.output_dir,
                  self.temp_dir, self.split_dir]:
            d.mkdir(parents=True, exist_ok=True)

    # =========================
    # 📂 路径生成（核心）
    # =========================
    def get_scan_dirs(self):
        """统一的 PDF 来源目录列表（字符串路径，便于直接传给 Path）"""
        return [str(p) for p in self.input_dirs]

    def get_split_path2(self, file_name):
        path = self.split_dir / file_name
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def get_split_path(self, folder_name, file_name):
        path = self.split_dir / folder_name / file_name
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    # 大多数 Linux 文件系统的单文件名字节上限
    MAX_FS_NAME_BYTES = 255

    @staticmethod
    def _truncate_utf8(text: str, max_bytes: int) -> str:
        """按字节裁剪 UTF-8 字符串，避免多字节字符被截断成乱码。"""
        if max_bytes <= 0:
            return ""
        encoded = text.encode("utf-8")
        if len(encoded) <= max_bytes:
            return text
        cut = encoded[:max_bytes]
        try:
            return cut.decode("utf-8")
        except UnicodeDecodeError:
            return cut.decode("utf-8", errors="ignore")

    def _safe_stem(self, value, fallback="file", max_bytes=None):
        """
        生成一个安全的文件名 stem（不含扩展名），并保证其 UTF-8 字节数
        不超过 max_bytes（默认按 255 字节文件名上限做预算，预留 .zip 等）。
        会尾随一个 8 位 hash 以便区分被截断到同一前缀的不同源文件。
        """
        raw = str(value or "").strip()
        if not raw:
            return fallback

        # 兼容从 Windows 入库的路径：Path("Z:\\a\\b.pdf").stem 在 Linux
        # 下不会把反斜杠识别为目录分隔符，需要先按两类分隔符切分。
        basename = re.split(r"[\\/]+", raw)[-1]
        stem = Path(basename).stem or fallback
        stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", stem)
        stem = re.sub(r"\s+", " ", stem).strip(" ._") or fallback

        digest = hashlib.md5(raw.encode("utf-8")).hexdigest()[:8]
        suffix = f"_{digest}"  # 9 字节 (ASCII)

        # 默认按文件名上限 255 字节，预留 .zip(4) + 余量(8) + suffix(9) = 25
        if max_bytes is None:
            max_bytes = self.MAX_FS_NAME_BYTES - len(suffix) - len(".zip") - 8

        # 至少给 stem 留 8 字节，否则降级成全 hash
        budget = max(8, max_bytes)
        stem = self._truncate_utf8(stem, budget).rstrip(" ._") or fallback

        return f"{stem}{suffix}"

    def get_download_path(self, file_name=None, task_id=None, file_path=None,
                           max_name_bytes=None):
        """
        下载文件路径（统一规范）
        优先级：task_id > file_path > file_name
        max_name_bytes：限制 stem 的字节预算，给“缩短重试”用
        """

        if task_id:
            name = self._safe_stem(
                file_name or file_path or str(task_id),
                fallback=str(task_id),
                max_bytes=max_name_bytes,
            )
            path = self.download_dir / str(task_id) / f"{name}.zip"
        elif file_path:
            name = self._safe_stem(file_path, max_bytes=max_name_bytes)
            path = self.download_dir / f"{name}.zip"
        else:
            name = self._safe_stem(file_name, max_bytes=max_name_bytes)
            path = self.download_dir / f"{name}.zip"

        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def shortened_download_paths(self, file_name=None, task_id=None, file_path=None):
        """
        在文件名长度上做几次降级尝试，依次产出候选路径供 caller 重试：
          1) 默认 stem 字节预算
          2) 80 字节
          3) 32 字节
          4) 8 字节（基本只剩 hash 8 位 + suffix）
        每个候选都自带不同长度 stem 的 hash 后缀，所以不会撞名。
        """
        # 第 1 个就是默认的，与 get_download_path 完全一致
        yield self.get_download_path(
            file_name=file_name, task_id=task_id, file_path=file_path
        )
        for budget in (80, 32, 8):
            yield self.get_download_path(
                file_name=file_name,
                task_id=task_id,
                file_path=file_path,
                max_name_bytes=budget,
            )

    def get_output_path(self, file_name, task_id=None):
        """
        输出文件路径（解析结果等）
        """
        if task_id:
            path = self.output_dir / str(task_id) / file_name
        else:
            path = self.output_dir / file_name

        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def get_temp_path(self, file_name, task_id=None):
        """
        临时文件路径
        """
        if task_id:
            path = self.temp_dir / str(task_id) / file_name
        else:
            path = self.temp_dir / file_name

        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    # =========================
    # 💾 写入
    # =========================

    def save_bytes(self, data: bytes, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "wb") as f:
            f.write(data)

        return path

    def save_text(self, text: str, path, encoding="utf-8"):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "w", encoding=encoding) as f:
            f.write(text)

        return path

    def save_stream(self, resp, path):
        """
        用于 requests streaming 下载
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "wb") as f:
            for chunk in resp.iter_content(8192):
                if chunk:
                    f.write(chunk)

        return path

    # =========================
    # 🔍 查询
    # =========================

    def exists(self, path):
        return Path(path).exists()

    def size(self, path):
        path = Path(path)
        return path.stat().st_size if path.exists() else 0

    # =========================
    # 🧹 清理
    # =========================

    def remove(self, path):
        path = Path(path)

        if path.is_file():
            path.unlink(missing_ok=True)

        elif path.is_dir():
            shutil.rmtree(path, ignore_errors=True)

    def cleanup_task(self, task_id):
        """
        删除某个任务的所有文件
        """
        for base in [self.download_dir, self.output_dir, self.temp_dir]:
            p = base / str(task_id)
            if p.exists():
                shutil.rmtree(p, ignore_errors=True)

    # =========================
    # 🔁 防重复（可选）
    # =========================

    def get_unique_path(self, path):
        """
        防止文件覆盖
        file.txt -> file_1.txt
        """
        path = Path(path)

        if not path.exists():
            return path

        stem = path.stem
        suffix = path.suffix
        parent = path.parent

        i = 1
        while True:
            new_path = parent / f"{stem}_{i}{suffix}"
            if not new_path.exists():
                return new_path
            i += 1
