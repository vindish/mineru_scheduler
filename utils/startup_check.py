from pathlib import Path

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


def _looks_like_mountpoint(p: Path) -> bool:
    """启发式判断是否像一个常见的挂载点路径，给出更清晰的报错提示。"""
    s = str(p).replace("\\", "/").lower()
    return any(seg in s for seg in ("/mnt/", "/media/", "/nfs/", "/nas/", "/share"))


def _count_pdfs(base: Path) -> int:
    n = 0
    try:
        for path in base.rglob("*"):
            if path.is_file() and path.suffix.lower() == ".pdf":
                n += 1
    except PermissionError:
        return -1
    return n


def run_checks():
    logger.info("🔍 启动自检开始...")

    # =========================
    # 🔐 TOKEN 检查
    # =========================
    if not TOKEN:
        raise RuntimeError("❌ MINERU_TOKEN 未配置（请在 .env 或环境变量中设置）")

    # =========================
    # 📂 PDF 来源目录检查（来自 settings 的统一列表）
    # 注意：这里不再自动创建，避免在容器里把未挂载的挂载点屏蔽掉。
    # =========================
    storage = Storage()  # noqa: F841 仅用于触发输出目录的创建

    if not PDF_INPUT_DIRS:
        raise RuntimeError("❌ PDF 来源目录未配置（settings.PDF_INPUT_DIRS 为空）")

    logger.info(f"📥 PDF 来源目录（共 {len(PDF_INPUT_DIRS)} 个）:")
    total_pdf = 0
    missing = []
    for d in PDF_INPUT_DIRS:
        if not d.exists():
            tip = "（看起来是挂载点，请确认宿主机已挂载、且 docker-compose 里有把它绑进容器）" \
                if _looks_like_mountpoint(d) else "（请确认路径正确；不会自动创建）"
            logger.error(f"  - 不存在: {d} {tip}")
            missing.append(d)
            continue
        if not d.is_dir():
            logger.error(f"  - 不是目录: {d}")
            missing.append(d)
            continue

        cnt = _count_pdfs(d)
        if cnt < 0:
            logger.error(f"  - 无权限读取: {d}")
            missing.append(d)
            continue
        total_pdf += cnt
        logger.info(f"  - {d}  (PDF 数量: {cnt})")

    if missing and len(missing) == len(PDF_INPUT_DIRS):
        # 全部不可用，直接拒绝启动，避免无意义空转
        raise RuntimeError(
            f"❌ 所有 PDF 来源目录都不可用，启动终止。请检查 PDF_INPUT_DIRS 与挂载配置：{missing}"
        )

    if total_pdf == 0:
        logger.warning("⚠️ 来源目录中暂未发现 PDF，调度器仍会启动并等待新文件。")

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
