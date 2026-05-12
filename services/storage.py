from pathlib import Path
from config.settings import BASE_DIR,DB_NAME,SCAN_DIRS
import hashlib
import re
import shutil
# 文件存储规范层
# 它负责统一管理“文件保存路径”和“文件是否存在”的逻辑
# 所有下载文件、输出文件，都应该通过它来管理路径


class Storage:
    """
    文件存储规范层（统一入口）
    """

    def __init__(self, base_dir=BASE_DIR):
        self.base_dir = Path(base_dir)

        # 目录分层
        self.pdf_dir = self.base_dir / "pdf"
        self.download_dir = self.base_dir / "download"
        self.output_dir = self.base_dir / "output"
        self.temp_dir = self.base_dir / "temp"
        self.split_dir = self.base_dir / "split"
        self.db_dir = self.base_dir / "db"

        # 初始化目录
        for d in [self.pdf_dir, self.download_dir, self.output_dir,
                   self.temp_dir,self.split_dir, self.db_dir]:
            d.mkdir(parents=True, exist_ok=True)

    # =========================
    # 📂 路径生成（核心）
    # =========================
    def get_db_path(self, db_name=DB_NAME):
        return self.db_dir / db_name

    def get_scan_dirs(self):
        return SCAN_DIRS

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
