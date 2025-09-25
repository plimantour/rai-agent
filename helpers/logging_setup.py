import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

_DEFAULT_FMT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DEFAULT_DATEFMT = "%Y-%m-%d %H:%M:%S"
_LOGGER_INITIALIZED_FLAG = "__APP_LOGGING_INITIALIZED__"

LEVEL_MAP = {
    "CRITICAL": logging.CRITICAL,
    "ERROR": logging.ERROR,
    "WARN": logging.WARNING,
    "WARNING": logging.WARNING,
    "INFO": logging.INFO,
    "DEBUG": logging.DEBUG,
    "TRACE": logging.DEBUG,  # no native trace; map to DEBUG
}

_CURRENT_LEVEL_NAME = None

# 3rd-party noisy libraries we want to quiet even at DEBUG root
_NOISY_LOGGERS = [
    "watchdog",
    "watchdog.observers",
    "watchdog.observers.inotify",
    "asyncio",
    "urllib3",
    "httpx",
    "httpcore",
]

def init_logging(level: Optional[str] = None,
                 log_dir: Optional[str] = None,
                 filename: str = "app.log",
                 max_bytes: int = 5_000_000,
                 backup_count: int = 5) -> None:
    """Initialize application-wide logging with a rotating file handler.

    Safe to call multiple times (idempotent). Environment overrides:
      APP_LOG_LEVEL, APP_LOG_DIR
    """
    if getattr(logging, _LOGGER_INITIALIZED_FLAG, False):
        return

    level_str = level or os.getenv("APP_LOG_LEVEL", "INFO").upper()
    log_level = LEVEL_MAP.get(level_str, logging.INFO)

    log_dir = log_dir or os.getenv("APP_LOG_DIR", "./logs")
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    log_path = Path(log_dir) / filename

    formatter = logging.Formatter(fmt=_DEFAULT_FMT, datefmt=_DEFAULT_DATEFMT)

    file_handler = RotatingFileHandler(log_path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(log_level)

    root = logging.getLogger()
    # Keep root at DEBUG so all events reach handlers; console handler still filters at desired level
    root.setLevel(logging.DEBUG)
    root.addHandler(file_handler)
    root.addHandler(console_handler)

    # Reduce noise from external libs if needed
    logging.getLogger("azure").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    for noisy in _NOISY_LOGGERS:
        logging.getLogger(noisy).setLevel(logging.WARNING)

    global _CURRENT_LEVEL_NAME
    _CURRENT_LEVEL_NAME = level_str
    setattr(logging, _LOGGER_INITIALIZED_FLAG, True)
    logging.getLogger(__name__).info(
        "Logging initialized: console_level=%s file_level=DEBUG path=%s max_bytes=%d backups=%d",
        level_str,
        log_path,
        max_bytes,
        backup_count,
    )


def get_logger(name: str) -> logging.Logger:
    """Return a module logger; ensures logging is initialized."""
    if not getattr(logging, _LOGGER_INITIALIZED_FLAG, False):
        init_logging()
    return logging.getLogger(name)


def set_log_level(level_name: str) -> bool:
    """Dynamically adjust log level for root & existing handlers.

    Returns True if level changed, False if invalid or unchanged.
    """
    if not getattr(logging, _LOGGER_INITIALIZED_FLAG, False):
        init_logging()
    if not level_name:
        return False
    upper = level_name.upper()
    if upper not in LEVEL_MAP:
        return False
    global _CURRENT_LEVEL_NAME
    if _CURRENT_LEVEL_NAME == upper:
        return False
    new_level = LEVEL_MAP[upper]
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    for h in root.handlers:
        try:
            if isinstance(h, RotatingFileHandler):
                h.setLevel(logging.DEBUG)
            else:
                h.setLevel(new_level)
        except Exception:
            pass
    # Re-apply noisy logger suppression
    for noisy in _NOISY_LOGGERS:
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _CURRENT_LEVEL_NAME = upper
    logging.getLogger(__name__).info("Log level changed dynamically to %s (console handler)", upper)
    return True

def get_current_log_level() -> str:
    return _CURRENT_LEVEL_NAME or logging.getLevelName(logging.getLogger().level)
