import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any


TECH_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
CONSOLE_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
ACTION_LOG_FORMAT = "%(asctime)s %(message)s"


def _level_from_env(name: str, default: str) -> int:
    raw_value = os.getenv(name, default).upper()
    return getattr(logging, raw_value, getattr(logging, default.upper(), logging.INFO))


def _int_from_env(name: str, default: int, min_value: int, max_value: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return max(min_value, min(value, max_value))


def _rotating_file_handler(path: Path, level: int, formatter: logging.Formatter) -> RotatingFileHandler:
    max_bytes = _int_from_env("LOG_FILE_MAX_MB", 10, 1, 1024) * 1024 * 1024
    backup_count = _int_from_env("LOG_FILE_BACKUP_COUNT", 5, 1, 100)
    handler = RotatingFileHandler(
        path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    handler.setLevel(level)
    handler.setFormatter(formatter)
    return handler


def configure_logging() -> None:
    log_dir = Path(os.getenv("LOG_DIR", "logs"))
    log_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.DEBUG)

    tech_formatter = logging.Formatter(TECH_LOG_FORMAT)
    console_formatter = logging.Formatter(CONSOLE_LOG_FORMAT)
    action_formatter = logging.Formatter(ACTION_LOG_FORMAT)

    file_level = _level_from_env("LOG_LEVEL", "INFO")
    console_level = _level_from_env("CONSOLE_LOG_LEVEL", "WARNING")
    action_level = _level_from_env("ACTION_LOG_LEVEL", "INFO")
    library_level = _level_from_env("LIBRARY_LOG_LEVEL", "WARNING")

    console_handler = logging.StreamHandler()
    console_handler.setLevel(console_level)
    console_handler.setFormatter(console_formatter)
    root.addHandler(console_handler)
    root.addHandler(_rotating_file_handler(log_dir / "bot.log", file_level, tech_formatter))

    for logger_name in ("aiogram", "aiohttp", "apscheduler"):
        logging.getLogger(logger_name).setLevel(library_level)

    action_logger = logging.getLogger("actions")
    action_logger.handlers.clear()
    action_logger.setLevel(action_level)
    action_logger.propagate = False

    action_console = logging.StreamHandler()
    action_console.setLevel(action_level)
    action_console.setFormatter(action_formatter)
    action_logger.addHandler(action_console)
    action_logger.addHandler(_rotating_file_handler(log_dir / "actions.log", action_level, action_formatter))


def actor_label(user: Any = None, user_id: Any = None) -> str:
    if user is not None:
        user_id = getattr(user, "id", user_id)
        username = getattr(user, "username", None)
        first_name = getattr(user, "first_name", None)
        last_name = getattr(user, "last_name", None)
    else:
        username = None
        first_name = None
        last_name = None

    parts = []
    if user_id:
        parts.append(str(user_id))
    if username:
        parts.append(f"@{username}")
    else:
        full_name = " ".join(part for part in [first_name, last_name] if part).strip()
        if full_name:
            parts.append(full_name)
    return " ".join(parts) if parts else "unknown"


def short_value(value: Any, max_len: int = 80) -> str:
    text = "" if value is None else str(value).replace("\n", " ").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 3].rstrip() + "..."


def action_event(category: str, message: str, **fields: Any) -> None:
    suffix = ""
    clean_fields = {
        key: short_value(value)
        for key, value in fields.items()
        if value is not None and value != ""
    }
    if clean_fields:
        suffix = " | " + " ".join(f"{key}={value}" for key, value in clean_fields.items())
    logging.getLogger("actions").info("[%s] %s%s", category.upper(), message, suffix)
