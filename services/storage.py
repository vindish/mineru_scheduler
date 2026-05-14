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

        # 兜底确保目录存在（settings 中已建过，这里再保一次幂等）
        for d in [self.pdf_dir, self.download_dir, self.output_dir,
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

    def _safe_stem(self, value, fallback="file"):
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
        max_len = 160
        if len(stem) > max_len:
            stem = stem[:max_len].rstrip(" ._")

        return f"{stem}_{digest}"

    def get_download_path(self, file_name=None, task_id=None, file_path=None):
        """
        下载文件路径（统一规范）
        优先级：task_id > file_path > file_name
        """

        if task_id:
            name = self._safe_stem(file_name or file_path or str(task_id), str(task_id))
            path = self.download_dir / str(task_id) / f"{name}.zip"

        elif file_path:
            name = self._safe_stem(file_path)
            path = self.download_dir / f"{name}.zip"
        else:
            name = self._safe_stem(file_name)
            path = self.download_dir / f"{name}.zip"

        path.parent.mkdir(parents=True, exist_ok=True)
        return path

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
