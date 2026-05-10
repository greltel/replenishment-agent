"""Centralized logging with loguru."""
from __future__ import annotations

import sys
from loguru import logger

from src.config import config


def setup_logger():
    """Configure loguru for both stdout and file output."""
    logger.remove()  # remove default handler

    # Console
    logger.add(
        sys.stdout,
        level=config.log_level,
        format="<green>{time:HH:mm:ss}</green> | "
               "<level>{level: <8}</level> | "
               "<cyan>{name}</cyan> - <level>{message}</level>",
        colorize=True,
    )

    # File (rotating)
    logger.add(
        config.log_dir / "agent_{time:YYYYMMDD}.log",
        level="DEBUG",
        rotation="00:00",
        retention="30 days",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
    )

    return logger


# Auto-setup on import
log = setup_logger()
