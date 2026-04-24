import logging
import sys
from datetime import datetime
from config.settings import LOG_DIR


log_file = LOG_DIR / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

logger = logging.getLogger("scheduler")
logger.setLevel(logging.INFO)

formatter = logging.Formatter(
    "%(asctime)s [%(levelname)s] [%(threadName)s] %(message)s"
)

# ✅ 控制台输出（关键！！）
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(formatter)
console_handler.stream.reconfigure(encoding='utf-8')

# ✅ 文件输出
file_handler = logging.FileHandler(log_file, encoding="utf-8")
file_handler.setFormatter(formatter)

logger.addHandler(console_handler)
logger.addHandler(file_handler)