from config.settings import (
    TOKEN,
    PDF_INPUT_DIRS,
    OUTPUT_BASE_DIR,
    DOWNLOAD_DIR,
    OUTPUT_DIR,
    SPLIT_DIR,
    TEMP_DIR,
    LOG_DIR,
)
from utils.logger import logger
from services.storage import Storage


def run_checks():
    logger.info("🔍 启动自检开始...")

    # =========================
    # 🔐 TOKEN 检查
    # =========================
    if not TOKEN:
        raise RuntimeError("❌ MINERU_TOKEN 未配置（请在 .env 或环境变量中设置）")

    # =========================
    # 📂 PDF 来源目录检查（来自 settings 的统一列表）
    # =========================
    storage = Storage()

    if not PDF_INPUT_DIRS:
        raise RuntimeError("❌ PDF 来源目录未配置（settings.PDF_INPUT_DIRS 为空）")

    logger.info(f"📥 PDF 来源目录（共 {len(PDF_INPUT_DIRS)} 个）:")
    total_pdf = 0
    for d in PDF_INPUT_DIRS:
        if not d.exists():
            logger.warning(f"  - 不存在，将自动创建: {d}")
            d.mkdir(parents=True, exist_ok=True)
        cnt = sum(1 for _ in d.rglob("*.pdf"))
        total_pdf += cnt
        logger.info(f"  - {d}  (PDF 数量: {cnt})")

    if total_pdf == 0:
        logger.warning("⚠️ 所有来源目录中均未发现 PDF，调度器仍会启动并等待新文件。")

    # =========================
    # 📤 输出目录检查
    # =========================
    logger.info("📤 输出目录:")
    logger.info(f"  - 输出根目录 OUTPUT_BASE_DIR : {OUTPUT_BASE_DIR}")
    logger.info(f"  - 下载结果   DOWNLOAD_DIR    : {DOWNLOAD_DIR}")
    logger.info(f"  - 解析输出   OUTPUT_DIR      : {OUTPUT_DIR}")
    logger.info(f"  - 拆分文件   SPLIT_DIR       : {SPLIT_DIR}")
    logger.info(f"  - 临时文件   TEMP_DIR        : {TEMP_DIR}")
    logger.info(f"  - 日志       LOG_DIR         : {LOG_DIR}")

    logger.info("✅ 配置检查通过")
