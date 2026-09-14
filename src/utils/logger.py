"""Explicit Loguru setup: console plus rotating UTF-8 application logs."""

import sys
from pathlib import Path

from loguru import logger

from src.core.exceptions import ConfigError
from src.utils.file_utils import get_app_root

__all__ = ["configure_logging", "logger"]


def configure_logging(
    log_dir: str | Path | None = None,
    *,
    level: str = "INFO",
    rotation: str | int = "10 MB",
    retention: str | int = "14 days",
) -> Path:
    """Configure application-wide sinks once at startup, or replace them on change.

    Importing this module does not create directories or files. Variable dumps
    are disabled in exception logs to avoid recording document data or secrets.
    """
    directory = Path(log_dir) if log_dir is not None else get_app_root() / "logs"
    log_path = directory / "app.log"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        logger.remove()
        if sys.stderr is not None:
            logger.add(sys.stderr, level=level, diagnose=False, backtrace=False)
        logger.add(
            log_path,
            level=level,
            encoding="utf-8",
            rotation=rotation,
            retention=retention,
            diagnose=False,
            backtrace=False,
        )
    except OSError as error:
        raise ConfigError(
            "Không thể mở nhật ký. Vui lòng kiểm tra quyền ghi."
        ) from error
    return log_path
