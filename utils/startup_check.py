import os
from config.settings import TOKEN
from utils.logger import logger
from pathlib import Path
from services.storage import Storage



def run_checks():
    logger.info("🔍 启动自检开始...")

    storage = Storage()

    pdf_dir = storage.pdf_dir
    db_dir = storage.db_dir

    # =========================
    # 🔐 TOKEN 检查
    # =========================
    if not TOKEN:
        raise RuntimeError("❌ TOKEN 未配置")

    # =========================
    # 📂 PDF目录检查
    # =========================
    if not any(pdf_dir.glob("*.pdf")):
        logger.warning(f"⚠️ PDF目录为空: {pdf_dir}")

    # =========================
    # 🗄️ DB目录检查
    # =========================
    db_dir.mkdir(parents=True, exist_ok=True)

    logger.info("✅ 配置检查通过")