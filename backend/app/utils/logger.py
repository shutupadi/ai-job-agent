"""Loguru-based structured logger used across the app."""

from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger

from app.config import settings

_CONFIGURED = False


def setup_logging() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    logger.remove()
    logger.add(
        sys.stdout,
        level=settings.log_level,
        colorize=True,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> "
            "| <level>{level:<7}</level> "
            "| <cyan>{name}:{line}</cyan> - <level>{message}</level>"
        ),
    )
    Path(settings.logs_dir).mkdir(parents=True, exist_ok=True)
    logger.add(
        settings.logs_dir / "app.log",
        level=settings.log_level,
        rotation="10 MB",
        retention=10,
        compression="zip",
        enqueue=True,
        backtrace=True,
        diagnose=False,
    )
    _CONFIGURED = True


# Auto-configure on import so any module getting the logger is ready.
setup_logging()
log = logger
