"""
Runtime logging configuration for the (p, Q) Collatz backend.

Outputs detailed execution logs to `logs/backend.log` (as well as console).
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_FILE = LOG_DIR / "backend.log"

_LOGGER_INITIALIZED = False


def get_logger(name: str = "collatz_backend") -> logging.Logger:
    """Return a configured logger that writes to logs/backend.log."""
    global _LOGGER_INITIALIZED
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger("collatz_backend")
    if not _LOGGER_INITIALIZED:
        root_logger.setLevel(logging.DEBUG)

        formatter = logging.Formatter(
            fmt="%(asctime)s | %(levelname)-7s | %(name)s:%(funcName)s:%(lineno)d | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        file_handler = RotatingFileHandler(
            LOG_FILE,
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

        _LOGGER_INITIALIZED = True
        root_logger.info("Logger initialized. Writing runtime logs to %s", LOG_FILE)

    if name == "collatz_backend":
        return root_logger
    return root_logger.getChild(name)

