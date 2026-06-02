import logging
import os
from pathlib import Path
from typing import List, Optional


logger = logging.getLogger(__name__)


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return

    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=env_path, override=False)
    else:
        load_dotenv(override=False)


def _parse_admin_ids(raw: str) -> List[int]:
    admin_ids: List[int] = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            admin_ids.append(int(item))
        except ValueError:
            logger.warning("Ignoring invalid ADMIN_IDS value: %r", item)
    return admin_ids


def _parse_int_env(
    name: str,
    default: int,
    *,
    min_value: Optional[int] = None,
    max_value: Optional[int] = None,
) -> int:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        logger.warning("Invalid integer env %s=%r; using default=%s", name, raw_value, default)
        return default

    if min_value is not None and value < min_value:
        logger.warning("Env %s=%s is below min=%s; clamping", name, value, min_value)
        value = min_value
    if max_value is not None and value > max_value:
        logger.warning("Env %s=%s is above max=%s; clamping", name, value, max_value)
        value = max_value
    return value


_load_env()

BOT_TOKEN: Optional[str] = os.getenv("BOT_TOKEN")
DEFAULT_NOTIFY_MODE = os.getenv("DEFAULT_NOTIFY_MODE", "discount")
ADMIN_IDS = _parse_admin_ids(os.getenv("ADMIN_IDS", ""))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
DATABASE_PATH = os.getenv("DATABASE_PATH", "trendyol_bot.db")
BACKUP_DIR = os.getenv("BACKUP_DIR", "backups")
MAX_SUBSCRIPTIONS_PER_USER = _parse_int_env("MAX_SUBSCRIPTIONS_PER_USER", 50, min_value=1, max_value=10000)
HEAVY_COMMAND_COOLDOWN_SECONDS = _parse_int_env("HEAVY_COMMAND_COOLDOWN_SECONDS", 20, min_value=0, max_value=3600)
# Kept for compatibility with older diagnostics/tests. The bot now always uses
# the package-based handler registration path.
USE_NEW_HANDLERS = True


def _check_bot_token() -> bool:
    if not BOT_TOKEN:
        raise ValueError(
            "BOT_TOKEN is not set.\n"
            "Set BOT_TOKEN in environment or .env file.\n"
            "Example: BOT_TOKEN=your_token_here"
        )
    return True
