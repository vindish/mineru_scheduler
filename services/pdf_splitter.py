# services/pdf_splitter.py

import math
import hashlib
from pathlib import Path
from PyPDF2 import PdfReader, PdfWriter


class PDFSplitter:

    def __init__(self, storage, max_pages=200,rate_limiter=None):
        self.storage = storage
        self.max_pages = max_pages
        self.rate_limiter = rate_limiter

    def _build_prefix(self, file_path):
        h = hashlib.md5(file_path.encode("utf-8")).hexdigest()[:8]
        name = Path(file_path).stem
        return f"{name}_{h}"

    def _write_pdf(self, writer, path):
        tmp = path.with_suffix(".tmp")
        with open(tmp, "wb") as f:
            writer.write(f)
        tmp.replace(path)

    def split(self, file_path):
        if hasattr(self, "rate_limiter") and self.rate_limiter:
            self.rate_limiter.acquire()
        # with open(file_path, "rb") as f:
        try:
            reader = PdfReader(file_path)
        except Exception as e:
            raise ValueError(f"PDF_INVALID: {e}")
        # reader = PdfReader(f)
        total = len(reader.pages)

        if total <= self.max_pages:
            return [file_path]

        prefix = self._build_prefix(file_path)
        parts = []
        
        for i in range(math.ceil(total / self.max_pages)):
            start = i * self.max_pages
            end = min((i + 1) * self.max_pages, total)
            folder = prefix
            new_path = self.storage.get_split_path(
                                        folder,
                                        f"{prefix}_p{i+1}.pdf"
                                    )

            if new_path.exists():
                parts.append(str(new_path))
                continue

            writer = PdfWriter()
            for p in range(start, end):
                writer.add_page(reader.pages[p])

            self._write_pdf(writer, new_path)
            parts.append(str(new_path))

        return parts