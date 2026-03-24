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
        load_dotenv(dotenv_path=env_path, override=True)
    else:
        load_dotenv(override=True)


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


_load_env()

BOT_TOKEN: Optional[str] = os.getenv("BOT_TOKEN")
DEFAULT_NOTIFY_MODE = os.getenv("DEFAULT_NOTIFY_MODE", "hourly")
ADMIN_IDS = _parse_admin_ids(os.getenv("ADMIN_IDS", ""))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
DATABASE_PATH = os.getenv("DATABASE_PATH", "trendyol_bot.db")
USE_NEW_HANDLERS = os.getenv("USE_NEW_HANDLERS", "false").lower() == "true"


def _check_bot_token() -> bool:
    if not BOT_TOKEN:
        raise ValueError(
            "BOT_TOKEN is not set.\n"
            "Set BOT_TOKEN in environment or .env file.\n"
            "Example: BOT_TOKEN=your_token_here"
        )
    return True
