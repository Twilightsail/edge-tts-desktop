"""日志文件与诊断信息。

日志写在数据目录的 logs/ 下并自动轮转（1 MB × 4 份），用户遇到问题时可在界面里导出。
日志只记录事件和错误类别，不记录用户文本、音频内容、令牌或 Azure 密钥。
"""

import logging
import platform
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import __version__

LOG_NAME = "backend.log"
FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def log_dir(data_dir: Path) -> Path:
    return data_dir / "logs"


def setup_logging(data_dir: Path) -> Path:
    folder = log_dir(data_dir)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / LOG_NAME
    file_handler = RotatingFileHandler(path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter(FORMAT))
    stream = logging.StreamHandler()
    stream.setFormatter(logging.Formatter(FORMAT))
    logging.basicConfig(level=logging.INFO, handlers=[stream, file_handler], force=True)
    logging.getLogger(__name__).info(
        "backend %s starting, python %s", __version__, sys.version.split()[0]
    )
    return path


def read_logs(data_dir: Path, limit: int = 1_000_000) -> str:
    """按时间顺序拼接各份日志，只取最后 limit 字节。"""
    base = log_dir(data_dir) / LOG_NAME
    files = [base.with_name(f"{LOG_NAME}.{i}") for i in (3, 2, 1)] + [base]
    chunks = []
    for path in files:
        try:
            chunks.append(path.read_bytes())
        except OSError:
            continue
    return b"".join(chunks)[-limit:].decode("utf-8", errors="replace")


def about(data_dir: Path) -> dict:
    try:
        import edge_tts

        edge_version = getattr(edge_tts, "__version__", "") or ""
    except Exception:
        edge_version = ""
    return {
        "version": __version__,
        "data_dir": str(data_dir),
        "log_file": str(log_dir(data_dir) / LOG_NAME),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "edge_tts": edge_version,
    }
