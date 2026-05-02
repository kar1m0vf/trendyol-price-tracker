import asyncio
import json
import logging
import sqlite3
import html
from typing import Optional, List, Tuple, Dict, Any, Union
from datetime import datetime, timedelta
import io
import re
import os
import csv
import time
import aiohttp
from urllib.parse import urlparse

from aiogram import Bot, Dispatcher, Router, types
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton
)

from config import BOT_TOKEN, _check_bot_token, USE_NEW_HANDLERS, DATABASE_PATH
from utils import get_next_notification_time
import aiogram
from logging_utils import action_event, configure_logging, short_value
from database import (
    init_db,
    add_user_if_not_exists,
    add_subscription,
    get_user_subscriptions,
    remove_subscription,
    iter_all_subscriptions,
    get_subscriptions_count,
    update_last_price,
    update_mode,
    set_user_language,
    get_user_language,
    remove_subscriptions_by_user,
    get_subscription,
    export_user_subscriptions,
    get_user_settings,
    update_notify_time,
    update_subscription_settings,
    update_user_settings,
    save_price_points_batch,
    get_bot_text,
    close_all_connections,
)
from localization import t, LOCALES


def _parse_kv_floats(text: Optional[str]) -> Dict[str, float]:
    """Parse key:value floats for keys min, max, percent.

    Returns a dict with any of keys 'min', 'max', 'percent' present as floats.
    Accepts comma or dot as decimal separator and optional percent sign for percent.
    """
    out: Dict[str, float] = {}
    if not text:
        return out

    patterns = {
        'min': r"\bmin\s*:\s*([0-9]+(?:[\.,][0-9]+)?)",
        'max': r"\bmax\s*:\s*([0-9]+(?:[\.,][0-9]+)?)",
        'percent': r"\bpercent\s*:\s*([0-9]+(?:[\.,][0-9]+)?)(?:\s*%|)"
    }
    for k, pat in patterns.items():
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            try:
                out[k] = float(m.group(1).replace(',', '.'))
            except ValueError:
                continue
    return out
from database import update_subscription_meta
from database import add_price_point, get_price_history, get_last_price_point, save_price_point, get_local_price_history
from database import get_price_stats, get_top_price_drops
from middleware import AntiSpamMiddleware
from scraper import (
    get_trending_all_top3_async,
    get_trending_by_search_top3_async,
    get_trending_by_category_top3_async,
    get_price_async,
    get_price_history_from_akakce_async,
    get_product_info_async,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from services.notification_service import NotificationService
from handlers.admin_handler import (
    admin_backup,
    admin_check_blocked,
    admin_cleanup,
    admin_main_menu,
    admin_recommend,
    admin_stats,
    admin_user_details,
    admin_user_details_callback,
    admin_users,
    admin_users_list_interactive,
    backup_database,
    cmd_admin,
    is_admin,
    submit_user_report,
    _admin_recommend_list,
)



configure_logging()
logger = logging.getLogger(__name__)


async def _send_progress_message(target, text: str, **kwargs):
    """Send a temporary status message for a user action."""
    try:
        if hasattr(target, "answer"):
            return await target.answer(text, **kwargs)
        return await _get_runtime_bot().send_message(target, text, **kwargs)
    except Exception:
        logger.debug("Failed to send progress message", exc_info=True)
        return None


async def _replace_progress_message(status_message, text: str, *, fallback_target=None, **kwargs) -> bool:
    """Edit a temporary status message into the final result."""
    if status_message is not None:
        try:
            await status_message.edit_text(text, **kwargs)
            return True
        except Exception:
            logger.debug("Failed to edit progress message", exc_info=True)

    if fallback_target is not None:
        sent = await _send_progress_message(fallback_target, text, **kwargs)
        return sent is not None
    return False


async def _clear_progress_message(status_message) -> bool:
    """Delete a temporary status message after a separate result was sent."""
    if status_message is None:
        return False
    try:
        await status_message.delete()
        return True
    except Exception:
        logger.debug("Failed to delete progress message", exc_info=True)
        return False


def _get_env_int(
    name: str,
    default: int,
    *,
    min_value: Optional[int] = None,
    max_value: Optional[int] = None,
) -> int:
    """Read integer env var with validation and safe fallback."""
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



CHECK_ALL_INTERVAL_MINUTES = _get_env_int(
    "CHECK_ALL_INTERVAL_MINUTES",
    60,
    min_value=1,
    max_value=24 * 60,
)
CHECK_ALL_FETCH_CONCURRENCY = _get_env_int(
    "CHECK_ALL_FETCH_CONCURRENCY",
    10,
    min_value=1,
    max_value=100,
)
DB_BACKUP_KEEP_FILES = _get_env_int(
    "DB_BACKUP_KEEP_FILES",
    7,
    min_value=1,
    max_value=365,
)
DB_BACKUP_HOUR = _get_env_int("DB_BACKUP_HOUR", 3, min_value=0, max_value=23)
DB_BACKUP_MINUTE = _get_env_int("DB_BACKUP_MINUTE", 0, min_value=0, max_value=59)


CHECK_ALL_JOB_ID = "check_all_interval"
BACKUP_JOB_ID = "db_backup_daily"

bot: Optional[Bot] = None
dp: Optional[Dispatcher] = None
router = Router(name="telegrambot")
notification_service: Optional[NotificationService] = None
_database_initialized = False
_middleware_configured = False


def create_app(
    *,
    initialize_database: bool = True,
    setup_middleware: bool = True,
) -> Tuple[Bot, Dispatcher]:
    """Create runtime objects needed to run polling.

    Importing this module should stay cheap: no Telegram session and no DB
    initialization happen until the application is explicitly created.
    """
    global bot, dp, notification_service, _database_initialized, _middleware_configured

    _check_bot_token()

    if bot is None:
        bot = Bot(token=BOT_TOKEN)
        notification_service = NotificationService(bot)

    if dp is None:
        dp = Dispatcher()
        dp.include_router(router)

    if initialize_database and not _database_initialized:
        init_db(run_maintenance=False)
        _database_initialized = True

    if setup_middleware and not _middleware_configured:
        dp.message.middleware(AntiSpamMiddleware())
        dp.callback_query.middleware(AntiSpamMiddleware())
        _middleware_configured = True

    return bot, dp


def _get_notification_service() -> NotificationService:
    if notification_service is None:
        raise RuntimeError("Bot runtime is not initialized. Call create_app() first.")
    return notification_service


def _get_runtime_bot() -> Bot:
    if bot is None:
        raise RuntimeError("Bot runtime is not initialized. Call create_app() first.")
    return bot


try:
    from config import DEFAULT_NOTIFY_MODE
except Exception:
    DEFAULT_NOTIFY_MODE = "discount"








last_health_check = 0
health_check_interval = 60


alert_edit_state = {}
report_state = {}


onboarding_state = {}


scheduler_lock = asyncio.Lock()
scheduler_start_lock = asyncio.Lock()
check_all_lock = asyncio.Lock()


def handle_blocked_user(user_id: int):
    """Remove all subscriptions from user who blocked the bot."""
    try:
        logger.info(f"Removing subscriptions for blocked user {user_id}")
        from database import remove_subscriptions_by_user
        remove_subscriptions_by_user(user_id)
        logger.info(f"Successfully removed subscriptions for user {user_id}")
    except Exception as e:
        logger.error(f"Failed to remove subscriptions for blocked user {user_id}: {e}")

async def send_notification_with_timeout(
    user_id: int,
    text: str,
    image: Optional[str] = None,
    timeout: float = 10.0,
    parse_mode: Optional[str] = None,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
) -> bool:
    """
    Send notification with timeout and proper error handling.

    Args:
        user_id: User ID
        text: Message text
        image: Photo URL (optional)
        timeout: Timeout in seconds

    Returns:
        True if sent successfully, False otherwise
    """

    try:
        return await _get_notification_service().send_notification_safe(
            user_id,
            text,
            image=image,
            timeout_seconds=timeout,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
        )
    except Exception:
        logger.exception("notification_service.send_notification_safe failed")
        return False


def convert_to_turkish_url(url: str) -> str:
    """Convert English Trendyol URL to Turkish version for better parsing"""
    if "/en/" in url:

        turkish_url = url.replace("/en/", "/")
        logger.info(f"Converted English URL to Turkish: {url} -> {turkish_url}")
        return turkish_url
    return url

async def resolve_short_url(url: str) -> str:
    """Resolve Trendyol short URLs (ty.gl) and convert to Turkish version"""
    original_url = url
    if "ty.gl/" in url:
        try:


            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(url, allow_redirects=True, timeout=10) as response:
                    final_url = str(response.url)
                    if "trendyol.com" in final_url:
                        url = final_url
        except Exception as e:
            logger.warning(f"Failed to resolve short URL {original_url}: {e}")


    url = convert_to_turkish_url(url)
    return url

def normalize_url(url: str) -> str:
    u = (url or "").strip()
    u = u.split("#", 1)[0]
    u = u.split("?", 1)[0]
    if u.endswith("/"):
        u = u[:-1]
    return u

def is_trendyol_product_url(u: str) -> bool:
    if not u or not isinstance(u, str):
        return False
    try:

        if len(u) > 2000:
            return False

        parsed = urlparse(u.strip())


        if parsed.scheme not in {"http", "https"}:
            return False


        host = (parsed.hostname or "").lower().rstrip(".")
        if not host:
            return False
        if host != "trendyol.com" and not host.endswith(".trendyol.com"):
            return False


        path = (parsed.path or "").lower()
        return ("/p/" in path or "-p-" in path)
    except (AttributeError, TypeError, UnicodeError):
        return False


def parse_date_flexible(date_str: str) -> Optional[datetime]:
    """
    Гибкий парсер дат в различных форматах.
    Пытается распарсить дату в нескольких популярных форматах.

    Args:
        date_str: Строка с датой

    Returns:
        datetime объект или None если парсинг не удался
    """
    if not date_str:
        return None

    date_str = date_str.strip()


    formats = [
        "%d.%m.%Y %H:%M:%S",
        "%d.%m.%Y %H:%M",
        "%d.%m.%Y",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%m/%d/%Y",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue

    logger.debug(f"Could not parse date: {date_str}")
    return None


def safe_ts_to_iso(ts_val) -> str:
    """Convert a timestamp-like value to ISO date string safely.
    Accepts int/float (epoch), ISO strings, or common date formats (dd.mm.YYYY).
    Falls back to str(ts_val) if parsing fails.
    """
    if ts_val is None:
        return ""
    if isinstance(ts_val, (int, float)):
        try:
            return datetime.fromtimestamp(int(ts_val)).isoformat()
        except Exception:
            return str(ts_val)
    if isinstance(ts_val, str):
        try:

            datetime.fromisoformat(ts_val)
            return ts_val
        except Exception:
            try:
                dt = datetime.strptime(ts_val, "%d.%m.%Y")
                return dt.isoformat()
            except Exception:
                return ts_val
    try:
        return str(ts_val)
    except Exception:
        return ""


async def send_notification_safe(
    user_id: int,
    text: str,
    image: Optional[str] = None,
    timeout_seconds: float = 10.0,
    parse_mode: Optional[str] = None,
) -> bool:
    """
    Безопасно отправляет уведомление с таймаутом.
    Имеет fallback на текстовое сообщение если фото не отправляется.

    Args:
        user_id: ID получателя
        text: Основной текст сообщения
        image: URL изображения (опционально)
        timeout_seconds: Таймаут в секундах

    Returns:
        True если успешно отправлено, False если ошибка
    """

    try:
        return await _get_notification_service().send_notification_safe(
            user_id,
            text,
            image=image,
            timeout_seconds=timeout_seconds,
            parse_mode=parse_mode,
        )
    except Exception:
        logger.exception("notification_service.send_notification_safe failed")
        return False

async def send_history_plot(user_id: int, url: str, hist):

    try:
        return await _get_notification_service().send_history_plot(user_id, url, hist)
    except Exception:
        logger.exception("notification_service.send_history_plot failed for user %s url=%s", user_id, url)
        try:
            await bot.send_message(user_id, t(user_id, "history_not_found"))
        except Exception:
            logger.exception("Failed to send fallback history_not_found message to %s", user_id)


async def send_history_for_subscription(user_id: int, sub_id: int, url: str):
    """Helper that prefers local DB history and falls back to akakce scraper."""

    local_hist = get_local_price_history(sub_id) if sub_id else None
    if local_hist and len(local_hist) >= 3:
        hist = local_hist
        logger.info(f"Local history: {len(hist)} points for sub={sub_id}")
    else:
        logger.info("Local history insufficient, falling back to Akakce for %s", url)
        hist = await get_price_history_from_akakce_async(url)

    if not hist or len(hist) < 3:
        await bot.send_message(user_id, "📊 История цен накапливается. Нужно минимум 3 дня данных для графика.")
        return

    await send_history_plot(user_id, url, hist)


from typing import List, Tuple, Set

TREND_SEARCH_AWAIT: Set[int] = set()

def trending_menu_kb(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=t(user_id, "trending_btn_all"), callback_data="trend:all"),
            InlineKeyboardButton(text=t(user_id, "trending_btn_category"), callback_data="trend:catmenu"),
            InlineKeyboardButton(text=t(user_id, "trending_btn_search"), callback_data="trend:search")
        ]
    ])

def trending_categories_kb(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=t(user_id, "trending_cat_electronics"), callback_data="trend:cat:electronics"),
            InlineKeyboardButton(text=t(user_id, "trending_cat_clothing"), callback_data="trend:cat:clothing"),
        ],
        [
            InlineKeyboardButton(text=t(user_id, "trending_cat_shoes"), callback_data="trend:cat:shoes"),
            InlineKeyboardButton(text=t(user_id, "trending_cat_home"), callback_data="trend:cat:home"),
        ],
    ])

def format_trending_items(user_id: int, items: List[Tuple[str, Optional[float], str]]) -> str:
    lines = []
    for title, price, url in items[:3]:
        title = (title or "").strip()
        if len(title) > 120:
            title = title[:117] + "..."
        price_str = f"{price} TL" if price is not None else t(user_id, "unknown_price")
        lines.append(f"• {title}\n{price_str}\n{url}")
    return "\n\n".join(lines)

async def send_trending_list(user_id: int, items: List[Tuple[str, Optional[float], str]]):
    if not items:
        await bot.send_message(user_id, t(user_id, "trending_unavailable"))
        return
    header = t(user_id, "trending_header")
    await bot.send_message(user_id, header + "\n\n" + format_trending_items(user_id, items))

def get_main_kb(user_id: int) -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=t(user_id, "btn_subscribe")), KeyboardButton(text=t(user_id, "btn_subs"))],
            [KeyboardButton(text=t(user_id, "btn_trending")), KeyboardButton(text=t(user_id, "btn_recommend"))],
            [KeyboardButton(text=t(user_id, "btn_language")), KeyboardButton(text=t(user_id, "btn_help"))]
        ],
        resize_keyboard=True
    )
    return kb

def get_notify_inline_kb(user_id: int, sub_id: Optional[int] = None) -> InlineKeyboardMarkup:

    if sub_id:
        return InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=t(user_id, "btn_mode_discount"), callback_data=f"mode:{sub_id}:discount"),
            InlineKeyboardButton(text=t(user_id, "btn_mode_hourly"), callback_data=f"mode:{sub_id}:hourly")
        ]])
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=t(user_id, "btn_mode_discount"), callback_data="mode:discount"),
        InlineKeyboardButton(text=t(user_id, "btn_mode_hourly"), callback_data="mode:hourly")
    ]])

def subscription_controls_kb_for_user(user_id: int, sub_id: int) -> InlineKeyboardMarkup:
    mode_label_hourly = t(user_id, "btn_mode_hourly")
    mode_label_discount = t(user_id, "btn_mode_discount")
    try:
        sub = get_subscription(sub_id)
        logger.debug("subscription_controls_kb_for_user: sub=%r", sub)
        if sub:

            try:
                mode_db = sub[3]
            except Exception:
                mode_db = None

            if mode_db == "hourly":
                mode_label_hourly = "✅ " + mode_label_hourly
            elif mode_db == "discount":
                mode_label_discount = "✅ " + mode_label_discount
    except Exception:
        logger.exception("Error building subscription controls kb for sub_id=%s", sub_id)

    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=mode_label_discount, callback_data=f"mode:{sub_id}:discount"),
            InlineKeyboardButton(text=mode_label_hourly, callback_data=f"mode:{sub_id}:hourly")
        ],
        [
            InlineKeyboardButton(text=t(user_id, "btn_history"), callback_data=f"history:{sub_id}"),
            InlineKeyboardButton(text=t(user_id, "btn_price_alert"), callback_data=f"alert_edit:{sub_id}")
        ],
        [
            InlineKeyboardButton(text=t(user_id, "btn_compare"), callback_data=f"compare:{sub_id}"),
            InlineKeyboardButton(text=t(user_id, "btn_unsubscribe_inline"), callback_data=f"unsubscribe:{sub_id}")
        ]
    ])


def _subscription_fields(sub: Tuple[Any, ...]) -> Dict[str, Any]:
    values = list(sub)
    while len(values) < 14:
        values.append(None)
    return {
        "sub_id": values[0],
        "user_id": values[1],
        "url": values[2],
        "mode": values[3],
        "last_price": values[4],
        "product_title": values[5],
        "product_image": values[6],
        "min_price": values[7],
        "max_price": values[8],
        "notify_percent": values[9],
        "notify_interval": values[10],
        "last_notify_time": values[11],
        "price_alert": values[12],
        "tags": values[13],
    }


def get_user_subscription_number(user_id: int, sub_id: int) -> Optional[int]:
    """Return the 1-based number shown to this user for a subscription."""
    try:
        for index, sub in enumerate(get_user_subscriptions(user_id), start=1):
            if sub and sub[0] == sub_id:
                return index
    except Exception:
        logger.debug("Failed to resolve public subscription number", exc_info=True)
    return None


def _subscription_public_label(user_id: int, sub_id: int) -> str:
    number = get_user_subscription_number(user_id, sub_id)
    return f"№ {number}" if number is not None else f"ID {sub_id}"


def resolve_user_subscription_ref(user_id: int, ref: str) -> Tuple[Optional[Tuple[Any, ...]], Optional[int]]:
    """Resolve a user-facing subscription number, with DB ID fallback.

    Users see numbers from their own list (1, 2, 3...). Callback data still uses
    the internal DB ID, and old command usages with real IDs continue to work
    when the number is outside the visible list range.
    """
    if not ref or not str(ref).isdigit():
        return None, None

    number = int(ref)
    try:
        subs = get_user_subscriptions(user_id)
    except Exception:
        logger.debug("Failed to load user subscriptions for ref resolution", exc_info=True)
        subs = []

    if 1 <= number <= len(subs):
        return subs[number - 1], number

    sub = get_subscription(number)
    if sub and len(sub) >= 2 and sub[1] == user_id:
        return sub, get_user_subscription_number(user_id, sub[0])

    return None, None


def _short_title(title: Optional[str], url: str, limit: int = 90) -> str:
    raw = (title or "").strip() or url
    raw = re.sub(r"\s+", " ", raw)
    if len(raw) <= limit:
        return raw
    return raw[: max(0, limit - 3)].rstrip() + "..."


def _format_price_for_user(user_id: int, price: Optional[float]) -> str:
    if price is None:
        return t(user_id, "unknown_price")
    try:
        return f"{float(price):.0f} TL"
    except (TypeError, ValueError):
        return t(user_id, "unknown_price")


def _mode_text_for_user(user_id: int, mode: Optional[str]) -> str:
    if mode == "hourly":
        return t(user_id, "mode_hourly")
    return t(user_id, "mode_discount")


def _product_link_html(user_id: int, url: str) -> str:
    safe_url = html.escape(url or "", quote=True)
    return f'<a href="{safe_url}">{html.escape(t(user_id, "subscription_card_open"))}</a>'


NotificationItem = Union[Tuple[str, Optional[str]], Dict[str, Any]]

_PRICE_NOTIFICATION_TITLE_KEYS = {
    "hourly": "notification_title_hourly",
    "discount_drop": "notification_title_discount_drop",
    "percent_drop": "notification_title_percent_drop",
    "percent_increase": "notification_title_percent_increase",
    "below_min": "notification_title_below_min",
    "above_max": "notification_title_above_max",
    "target_hit": "notification_title_target_hit",
}

_PRICE_NOTIFICATION_ICONS = {
    "hourly": "🔔",
    "discount_drop": "📉",
    "percent_drop": "📉",
    "percent_increase": "📈",
    "below_min": "📊",
    "above_max": "📊",
    "target_hit": "🎯",
}


def _notification_title_for_reason(user_id: int, reason: str) -> str:
    key = _PRICE_NOTIFICATION_TITLE_KEYS.get(reason, "notification_title_hourly")
    return t(user_id, key)


def _notification_icon_for_reason(reason: str) -> str:
    return _PRICE_NOTIFICATION_ICONS.get(reason, "🔔")


def _format_notification_percent(percent: Optional[float]) -> Optional[str]:
    if percent is None:
        return None
    try:
        value = float(percent)
    except (TypeError, ValueError):
        return None
    if abs(value) < 0.05:
        value = 0.0
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.1f}%"


def _price_notification_keyboard(user_id: int, sub_id: int, url: str) -> InlineKeyboardMarkup:
    rows = []
    if url:
        rows.append([
            InlineKeyboardButton(text=t(user_id, "btn_view_product"), url=url)
        ])
    rows.append([
        InlineKeyboardButton(text=t(user_id, "btn_history"), callback_data=f"history:{sub_id}"),
        InlineKeyboardButton(text=t(user_id, "btn_edit"), callback_data=f"edit_sub:{sub_id}"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _grouped_notifications_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=t(user_id, "btn_subs"), callback_data="subs:list")
    ]])


def format_price_notification(
    user_id: int,
    *,
    reason: str,
    sub_id: int,
    url: str,
    title: Optional[str],
    current_price: float,
    old_price: Optional[float] = None,
    percent: Optional[float] = None,
    target_price: Optional[float] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
) -> str:
    title_text = html.escape(_short_title(title, url, limit=110))
    public_label = html.escape(_subscription_public_label(user_id, sub_id))
    current_price_text = html.escape(_format_price_for_user(user_id, current_price))
    icon = _notification_icon_for_reason(reason)
    reason_title = html.escape(_notification_title_for_reason(user_id, reason))

    lines = [
        f"{icon} <b>{reason_title}</b>",
        "",
        f"<code>{public_label}</code> <b>{title_text}</b>",
        f"💰 {html.escape(t(user_id, 'current_price'))}: <b>{current_price_text}</b>",
    ]

    if old_price is not None:
        old_price_text = html.escape(_format_price_for_user(user_id, old_price))
        lines.append(
            f"↩️ {html.escape(t(user_id, 'notification_previous_price'))}: <s>{old_price_text}</s>"
        )

    percent_text = _format_notification_percent(percent)
    if percent_text is not None:
        lines.append(
            f"📊 {html.escape(t(user_id, 'notification_change'))}: "
            f"<b>{html.escape(percent_text)}</b>"
        )

    if target_price is not None:
        target_text = html.escape(_format_price_for_user(user_id, target_price))
        lines.append(
            f"🎯 {html.escape(t(user_id, 'notification_target_price'))}: <b>{target_text}</b>"
        )
    if min_price is not None:
        min_text = html.escape(_format_price_for_user(user_id, min_price))
        lines.append(
            f"⬇️ {html.escape(t(user_id, 'min_price_label'))}: <b>{min_text}</b>"
        )
    if max_price is not None:
        max_text = html.escape(_format_price_for_user(user_id, max_price))
        lines.append(
            f"⬆️ {html.escape(t(user_id, 'max_price_label'))}: <b>{max_text}</b>"
        )

    lines.extend(["", html.escape(t(user_id, "notification_open_hint"))])
    return "\n".join(lines)


def summarize_price_notification(
    user_id: int,
    *,
    reason: str,
    sub_id: int,
    url: str,
    title: Optional[str],
    current_price: float,
    old_price: Optional[float] = None,
    percent: Optional[float] = None,
    target_price: Optional[float] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
) -> str:
    title_text = html.escape(_short_title(title, url, limit=80))
    public_label = html.escape(_subscription_public_label(user_id, sub_id))
    current_price_text = html.escape(_format_price_for_user(user_id, current_price))
    icon = _notification_icon_for_reason(reason)

    details = [f"{html.escape(t(user_id, 'current_price'))}: <b>{current_price_text}</b>"]
    if old_price is not None:
        old_price_text = html.escape(_format_price_for_user(user_id, old_price))
        details.insert(0, f"<s>{old_price_text}</s> → <b>{current_price_text}</b>")
    percent_text = _format_notification_percent(percent)
    if percent_text is not None:
        details.append(f"{html.escape(t(user_id, 'notification_change'))}: <b>{html.escape(percent_text)}</b>")
    if target_price is not None:
        details.append(
            f"{html.escape(t(user_id, 'notification_target_price'))}: "
            f"<b>{html.escape(_format_price_for_user(user_id, target_price))}</b>"
        )
    if min_price is not None:
        details.append(
            f"{html.escape(t(user_id, 'min_price_label'))}: "
            f"<b>{html.escape(_format_price_for_user(user_id, min_price))}</b>"
        )
    if max_price is not None:
        details.append(
            f"{html.escape(t(user_id, 'max_price_label'))}: "
            f"<b>{html.escape(_format_price_for_user(user_id, max_price))}</b>"
        )

    return f"{icon} <code>{public_label}</code> <b>{title_text}</b>\n   " + " · ".join(details)


def build_price_notification_payload(
    user_id: int,
    *,
    reason: str,
    sub_id: int,
    url: str,
    title: Optional[str],
    image: Optional[str],
    current_price: float,
    old_price: Optional[float] = None,
    percent: Optional[float] = None,
    target_price: Optional[float] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
) -> Dict[str, Any]:
    common = {
        "user_id": user_id,
        "reason": reason,
        "sub_id": sub_id,
        "url": url,
        "title": title,
        "current_price": current_price,
        "old_price": old_price,
        "percent": percent,
        "target_price": target_price,
        "min_price": min_price,
        "max_price": max_price,
    }
    return {
        "text": format_price_notification(**common),
        "summary_html": summarize_price_notification(**common),
        "image": image,
        "reply_markup": _price_notification_keyboard(user_id, sub_id, url),
        "parse_mode": "HTML",
    }


def _notification_delivery_parts(
    notification: NotificationItem,
) -> Tuple[str, Optional[str], Optional[InlineKeyboardMarkup], Optional[str]]:
    if isinstance(notification, dict):
        return (
            str(notification.get("text") or ""),
            notification.get("image"),
            notification.get("reply_markup"),
            notification.get("parse_mode"),
        )

    text, image = notification
    return text, image, None, None


def _notification_summary_html(notification: NotificationItem) -> str:
    if isinstance(notification, dict):
        summary = notification.get("summary_html")
        if summary:
            return str(summary)
        return html.escape(str(notification.get("text") or ""))

    text, _image = notification
    return html.escape(text)


def format_subscription_added_card(
    user_id: int,
    sub_id: int,
    url: str,
    title: Optional[str],
    price: Optional[float],
    mode: Optional[str],
) -> str:
    title_text = html.escape(_short_title(title, url, limit=120))
    price_text = html.escape(_format_price_for_user(user_id, price))
    mode_text = html.escape(_mode_text_for_user(user_id, mode))
    if price is None:
        hint_key = "subscription_added_hint_waiting_price"
    else:
        hint_key = "subscription_added_hint_hourly" if mode == "hourly" else "subscription_added_hint_discount"
    hint = html.escape(t(user_id, hint_key))
    public_label = html.escape(_subscription_public_label(user_id, sub_id))

    return "\n".join([
        f"<b>{html.escape(t(user_id, 'subscription_added_header'))}</b>",
        "",
        f"<b>{title_text}</b>",
        f"<code>{public_label}</code>",
        f"💰 {html.escape(t(user_id, 'current_price'))}: <b>{price_text}</b>",
        f"🔔 {html.escape(t(user_id, 'mode'))}: {mode_text}",
        f"ℹ️ {hint}",
        "",
        _product_link_html(user_id, url),
    ])


def format_subscription_card(user_id: int, sub: Tuple[Any, ...]) -> str:
    data = _subscription_fields(sub)
    sub_id = data["sub_id"]
    url = data["url"] or ""
    public_label = html.escape(_subscription_public_label(user_id, sub_id))
    title_text = html.escape(_short_title(data["product_title"], url))
    price_text = html.escape(_format_price_for_user(user_id, data["last_price"]))
    mode_text = html.escape(_mode_text_for_user(user_id, data["mode"]))
    status_text = t(user_id, "status_active") if data["last_price"] is not None else t(user_id, "status_waiting_price")
    status_icon = "✅" if data["last_price"] is not None else "⏳"
    next_notify = html.escape(
        get_next_notification_time(
            data["mode"],
            data["last_notify_time"],
            data["notify_interval"],
            user_id,
            t,
        )
    )

    lines = [
        f"{status_icon} <b>{html.escape(status_text)}</b> | <code>{public_label}</code>",
        f"📦 <b>{title_text}</b>",
        f"💰 {html.escape(t(user_id, 'current_price'))}: <b>{price_text}</b>",
        f"🔔 {html.escape(t(user_id, 'mode'))}: {mode_text}",
        f"⏱ {html.escape(t(user_id, 'subscription_card_next'))}: {next_notify}",
    ]

    if data["price_alert"] is not None:
        lines.append(
            f"🎯 {html.escape(t(user_id, 'price_alert_label'))}: "
            f"{html.escape(_format_price_for_user(user_id, data['price_alert']))}"
        )
    if data["min_price"] is not None:
        lines.append(
            f"📉 {html.escape(t(user_id, 'min_price_label'))}: "
            f"{html.escape(_format_price_for_user(user_id, data['min_price']))}"
        )
    if data["max_price"] is not None:
        lines.append(
            f"📈 {html.escape(t(user_id, 'max_price_label'))}: "
            f"{html.escape(_format_price_for_user(user_id, data['max_price']))}"
        )
    if data["notify_percent"] is not None:
        try:
            lines.append(f"📊 {html.escape(t(user_id, 'notify_percent'))}: {float(data['notify_percent']):.1f}%")
        except (TypeError, ValueError):
            pass

    lines.extend(["", _product_link_html(user_id, url)])
    return "\n".join(lines)


def build_subscriptions_overview(
    user_id: int,
    subs: List[Tuple[Any, ...]],
    *,
    max_chars: int = 3600,
) -> Tuple[str, InlineKeyboardMarkup]:
    lines = [html.escape(t(user_id, "mysubs_summary").format(count=len(subs))), ""]
    button_rows = []
    shown = 0

    for index, sub in enumerate(subs, start=1):
        data = _subscription_fields(sub)
        sub_id = data["sub_id"]
        url = data["url"] or ""
        title = _short_title(data["product_title"], url, limit=58)
        title_html = html.escape(title)
        price_text = html.escape(_format_price_for_user(user_id, data["last_price"]))
        mode_text = html.escape(_mode_text_for_user(user_id, data["mode"]))
        status_icon = "✅" if data["last_price"] is not None else "⏳"

        line = (
            f"{status_icon} <code>№ {index}</code> "
            f"<b>{title_html}</b>\n"
            f"   💰 {price_text} · 🔔 {mode_text}"
        )
        if data["price_alert"] is not None:
            line += f" · 🎯 {html.escape(_format_price_for_user(user_id, data['price_alert']))}"

        tentative = "\n".join(lines + [line])
        if shown > 0 and len(tentative) > max_chars:
            break

        lines.append(line)
        button_title = _short_title(data["product_title"], url, limit=36)
        button_rows.append([
            InlineKeyboardButton(
                text=f"№ {index} · {button_title}",
                callback_data=f"edit_sub:{sub_id}",
            )
        ])
        shown += 1

    if shown < len(subs):
        lines.extend([
            "",
            html.escape(t(user_id, "mysubs_limit_notice").format(shown=shown, total=len(subs))),
        ])

    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=button_rows)


async def send_subscription_added_message(
    message: types.Message,
    user_id: int,
    sub_id: int,
    url: str,
    title: Optional[str],
    price: Optional[float],
    image: Optional[str],
    mode: Optional[str],
) -> None:
    text = format_subscription_added_card(user_id, sub_id, url, title, price, mode)
    controls = subscription_controls_kb_for_user(user_id, sub_id)

    if image:
        try:
            await message.answer_photo(
                photo=image,
                caption=text,
                reply_markup=controls,
                parse_mode="HTML",
            )
            return
        except Exception as exc:
            logger.debug("Failed to send subscription photo for sub %s: %s", sub_id, exc)

    await message.answer(text, reply_markup=controls, parse_mode="HTML")


async def cmd_start_old(message: types.Message):
    user_id = message.from_user.id
    add_user_if_not_exists(user_id)


    if user_id not in onboarding_state:
        onboarding_state[user_id] = "welcome"
        await send_onboarding_step(user_id, message)
    else:
        await message.answer(
            t(user_id, "start_text"),
            reply_markup=get_main_kb(user_id),
            parse_mode="Markdown",
        )

async def send_onboarding_step(user_id: int, message: types.Message):
    """Send current onboarding step"""
    step = onboarding_state.get(user_id, "welcome")

    if step == "welcome":

        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text=t(user_id, "onboarding_try"))],
                [KeyboardButton(text=t(user_id, "onboarding_skip"))]
            ],
            resize_keyboard=True
        )
        await message.answer(
            t(user_id, "onboarding_welcome"),
            reply_markup=kb,
            parse_mode="Markdown",
        )
        onboarding_state[user_id] = "waiting_try"

    elif step == "waiting_try":

        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text=t(user_id, "onboarding_done"))],
                [KeyboardButton(text=t(user_id, "onboarding_help"))]
            ],
            resize_keyboard=True
        )
        await message.answer(
            t(user_id, "onboarding_explain"),
            reply_markup=kb,
            parse_mode="Markdown",
        )
        onboarding_state[user_id] = "explained"

    elif step == "explained":

        del onboarding_state[user_id]
        await message.answer(
            t(user_id, "onboarding_complete"),
            reply_markup=get_main_kb(user_id),
            parse_mode="Markdown",
        )

def _filter_language_button(message: types.Message) -> bool:
    """Filter for language button"""
    if not message.text or not message.from_user:
        return False
    return message.text == t(message.from_user.id, "btn_language")

def _filter_help_button(message: types.Message) -> bool:
    """Filter for help button"""
    if not message.text or not message.from_user:
        return False
    return message.text == t(message.from_user.id, "btn_help")

def _filter_onboarding_try(message: types.Message) -> bool:
    """Filter for onboarding try button"""
    if not message.text or not message.from_user:
        return False
    return message.text == t(message.from_user.id, "onboarding_try")

def _filter_onboarding_skip(message: types.Message) -> bool:
    """Filter for onboarding skip button"""
    if not message.text or not message.from_user:
        return False
    return message.text == t(message.from_user.id, "onboarding_skip")

def _filter_onboarding_done(message: types.Message) -> bool:
    """Filter for onboarding done button"""
    if not message.text or not message.from_user:
        return False
    return message.text == t(message.from_user.id, "onboarding_done")

@router.message(_filter_language_button)
async def cmd_lang_message(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=t(message.from_user.id, "lang_ru"), callback_data="lang:ru"),
            InlineKeyboardButton(text=t(message.from_user.id, "lang_en"), callback_data="lang:en")
        ],
        [
            InlineKeyboardButton(text=t(message.from_user.id, "lang_az"), callback_data="lang:az"),
            InlineKeyboardButton(text=t(message.from_user.id, "lang_tr"), callback_data="lang:tr")
        ]
    ])
    await message.answer(t(message.from_user.id, "choose_language"), reply_markup=kb)

@router.message(_filter_help_button)
async def cmd_help_button(message: types.Message):
    """Handle help button press"""
    await cmd_help_old(message)

@router.message(_filter_onboarding_try)
async def cmd_onboarding_try(message: types.Message):
    """Handle onboarding try button"""
    user_id = message.from_user.id
    await send_onboarding_step(user_id, message)

@router.message(_filter_onboarding_skip)
async def cmd_onboarding_skip(message: types.Message):
    """Handle onboarding skip button"""
    user_id = message.from_user.id
    if user_id in onboarding_state:
        del onboarding_state[user_id]
    await message.answer(
        t(user_id, "onboarding_skipped"),
        reply_markup=get_main_kb(user_id),
        parse_mode="Markdown",
    )

@router.message(_filter_onboarding_done)
async def cmd_onboarding_done(message: types.Message):
    """Handle onboarding done button"""
    user_id = message.from_user.id
    if user_id in onboarding_state:
        del onboarding_state[user_id]
    await message.answer(
        t(user_id, "onboarding_complete"),
        reply_markup=get_main_kb(user_id),
        parse_mode="Markdown",
    )

@router.message(Command("language"))
async def cmd_language_command(message: types.Message):
    parts = (message.text or "").split()
    if len(parts) > 1:
        code = parts[1].lower()
        if code in {"ru", "en", "az", "tr"}:
            set_user_language(message.from_user.id, code)
            try:
                await message.answer(t(message.from_user.id, "lang_changed"))
            except Exception as e:
                logger.exception("Failed to send lang_changed message: %s", e)
            try:
                await bot.send_message(
                    message.from_user.id,
                    t(message.from_user.id, "start_text"),
                    reply_markup=get_main_kb(message.from_user.id),
                    parse_mode="Markdown",
                )
            except Exception as e:
                logger.exception("Failed to send start_text after language change: %s", e)
        else:
            await message.answer(t(message.from_user.id, "invalid_language"))
    else:
        await cmd_lang_message(message)



async def cmd_help_old(message: types.Message):
    user_id = message.from_user.id
    args = message.text.split()

    if len(args) > 1 and args[1].lower() == "full":
        await message.answer(t(user_id, "help_full"))
    else:

        help_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=t(user_id, "btn_detailed_help"), callback_data="help:full")]
        ])
        await message.answer(t(user_id, "help_text"), reply_markup=help_keyboard)

@router.message(Command("report"))
async def cmd_report(message: types.Message):
    """Handle user reports/support requests"""
    user_id = message.from_user.id
    parts = (message.text or "").split(maxsplit=1)

    if len(parts) < 2:

        report_state[user_id] = {"step": "waiting_text"}
        await message.answer(t(user_id, "report_prompt"))
        return


    report_text = parts[1].strip()
    if len(report_text) < 5:
        await message.answer(t(user_id, "report_too_short"))
        return

    await submit_user_report(user_id, report_text, message)


async def cmd_mysubs_cmd_old(message: types.Message):
    await cmd_mysubs(message)

@router.message(Command("history"))
async def cmd_history(message: types.Message):
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(t(message.from_user.id, "cmd_history_usage"))
        return
    arg = parts[1].strip()


    if arg.isdigit():
        sub, _public_number = resolve_user_subscription_ref(message.from_user.id, arg)
        if not sub:
            await message.answer(t(message.from_user.id, "no_subs"))
            return
        sid = sub[0]

        if len(sub) >= 13:
            url = sub[2]
        elif len(sub) >= 12:
            url = sub[2]
        else:
            url = sub[2] if len(sub) > 2 else ""
        status_message = await _send_progress_message(
            message,
            t(message.from_user.id, "status_loading_history"),
        )

        db_hist = get_price_history(sid, limit=1000)
        if db_hist and len(db_hist) >= 2:

            hist = [(safe_ts_to_iso(r[0]), r[1]) for r in db_hist]
            try:
                await send_history_plot(message.from_user.id, url, hist)
                await _clear_progress_message(status_message)
            except Exception as e:
                logger.exception("history plot send failed: %s", e)
                await _replace_progress_message(
                    status_message,
                    t(message.from_user.id, "error_generic"),
                    fallback_target=message,
                )
            return


        try:
            hist = await get_price_history_from_akakce_async(url)
        except Exception as e:
            logger.exception("history fetch failed: %s", e)
            await _replace_progress_message(
                status_message,
                t(message.from_user.id, "error_generic"),
                fallback_target=message,
            )
            return
        if not hist:
            await _replace_progress_message(
                status_message,
                t(message.from_user.id, "history_not_found"),
                fallback_target=message,
            )
            return

        try:
            for d_str, p in hist[-30:]:
                try:

                    ts = None
                    if isinstance(d_str, str):
                        try:
                            dt = datetime.fromisoformat(d_str)
                            ts = int(dt.timestamp())
                        except Exception:
                            try:
                                dt2 = datetime.strptime(d_str, "%d.%m.%Y")
                                ts = int(dt2.timestamp())
                            except Exception:
                                ts = None
                    add_price_point(sid, url, float(p), ts=ts or None, source='akakce')
                except Exception:
                    continue
        except Exception:
            logger.exception("Failed to save akakce history into DB for sub %s", sid)

        try:
            await send_history_plot(message.from_user.id, url, hist)
            await _clear_progress_message(status_message)
        except Exception as e:
            logger.exception("history plot send failed: %s", e)
            await _replace_progress_message(
                status_message,
                t(message.from_user.id, "error_generic"),
                fallback_target=message,
            )
        return


    url = normalize_url(arg)
    if "trendyol.com" not in url.lower():
        await message.answer(t(message.from_user.id, "not_trendyol"))
        return
    if not is_trendyol_product_url(url):
        await message.answer(t(message.from_user.id, "not_product_url"))
        return

    status_message = await _send_progress_message(
        message,
        t(message.from_user.id, "status_loading_history"),
    )
    try:
        hist = await get_price_history_from_akakce_async(url)
    except Exception as e:
        logger.exception("history fetch failed: %s", e)
        await _replace_progress_message(
            status_message,
            t(message.from_user.id, "error_generic"),
            fallback_target=message,
        )
        return
    if not hist:
        await _replace_progress_message(
            status_message,
            t(message.from_user.id, "history_not_found"),
            fallback_target=message,
        )
        return
    try:
        await send_history_plot(message.from_user.id, url, hist)
        await _clear_progress_message(status_message)
    except Exception as e:
        logger.exception("history plot send failed: %s", e)
        await _replace_progress_message(
            status_message,
            t(message.from_user.id, "error_generic"),
            fallback_target=message,
        )


async def cmd_unsubscribe_old(message: types.Message):
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer(t(message.from_user.id, "provide_subscription_id"))
        return
    sub, _public_number = resolve_user_subscription_ref(message.from_user.id, parts[1])
    if not sub:
        await message.answer(t(message.from_user.id, "no_subs"))
        return
    sid = sub[0]
    try:
        remove_subscription(sid)
        await message.answer(t(message.from_user.id, "sub_removed"))
    except Exception:
        await message.answer(t(message.from_user.id, "error_generic"))


cmd_unsubscribe = cmd_unsubscribe_old

@router.message(Command("setmode"))
async def cmd_setmode(message: types.Message):
    parts = (message.text or "").split()
    if len(parts) < 3 or not parts[1].isdigit():
        await message.answer(t(message.from_user.id, "cmd_setmode_usage"))
        return
    sub, _public_number = resolve_user_subscription_ref(message.from_user.id, parts[1])
    if not sub:
        await message.answer(t(message.from_user.id, "no_subs_found_id"))
        return
    sid = sub[0]
    mode = parts[2].lower()
    if mode not in {"hourly", "discount"}:
        await message.answer(t(message.from_user.id, "provide_mode_options"))
        return
    try:

        if len(sub) >= 2 and sub[1] != message.from_user.id:
            await message.answer(t(message.from_user.id, "no_subs_found_id"))
            return
    except Exception:
        pass

    try:
        try:
            update_mode(sid, mode)
        except Exception as e:
            logger.exception("update_mode error in /setmode for sub %s: %s", sid, e)
            await message.answer(t(message.from_user.id, "error_generic"))
            return

        await message.answer(t(message.from_user.id, "mode_changed").format(mode=mode))
    except aiogram.exceptions.TelegramAPIError as e:
        logger.error("Telegram API error in /setmode: %s", e)
        await message.answer(t(message.from_user.id, "error_generic"))
    except Exception as e:
        logger.exception("Unexpected error in /setmode: %s", e)
        await message.answer(t(message.from_user.id, "error_generic"))

@router.message(Command("price_alert"))
async def cmd_price_alert(message: types.Message):
    """Установить целевую цену для уведомлений"""
    user_id = message.from_user.id
    parts = (message.text or "").split()
    if len(parts) < 3:
        await message.answer(t(user_id, "price_alert_usage"))
        return

    if not parts[1].isdigit():
        await message.answer(t(user_id, "price_alert_id_must_be_number"))
        return

    sub, _public_number = resolve_user_subscription_ref(user_id, parts[1])
    if not sub:
        await message.answer(t(user_id, "price_alert_sub_not_found"))
        return
    sid = sub[0]

    try:
        target_price = float(parts[2])
    except ValueError:
        await message.answer(t(user_id, "price_alert_price_must_be_number"))
        return

    if target_price < 0:
        await message.answer(t(user_id, "price_alert_price_negative"))
        return

    try:
        update_subscription_settings(sid, price_alert=target_price)
        current_price = sub[4] if len(sub) > 4 else None


        if current_price is not None and current_price <= target_price:
            await message.answer(
                t(user_id, "price_alert_set_success_already_below").format(
                    target=target_price,
                    current=current_price
                )
            )
        else:
            await message.answer(
                t(user_id, "price_alert_set_success").format(price=target_price)
            )
    except Exception:
        logger.exception("Error setting price_alert")
        await message.answer(t(user_id, "price_alert_set_error"))

@router.message(Command("about"))
async def cmd_about(message: types.Message):
    await message.answer(t(message.from_user.id, "about_text"))

@router.message(Command("ping"))
async def cmd_ping(message: types.Message):
    await message.answer(t(message.from_user.id, "ping_pong"))

@router.message(Command("settings"))
async def cmd_settings(message: types.Message):
    """Команда для настройки уведомлений"""
    try:
        parts = (message.text or "").split()
        if len(parts) < 2:
            await message.answer(t(message.from_user.id, "settings_usage"))
            return

        subcmd = parts[1].lower()

        if subcmd == "quiet":
            if len(parts) == 4 and parts[2].isdigit() and parts[3].isdigit():
                start = int(parts[2])
                end = int(parts[3])
                if 0 <= start <= 23 and 0 <= end <= 23:
                    update_user_settings(
                        message.from_user.id,
                        notify_quiet_hours_start=start,
                        notify_quiet_hours_end=end
                    )
                    await message.answer(
                        t(message.from_user.id, "quiet_hours_set").format(start=start, end=end)
                    )
                    return
            await message.answer(t(message.from_user.id, "quiet_hours_usage"))

        elif subcmd == "price":
            if len(parts) >= 4 and parts[2].isdigit():
                sub, _public_number = resolve_user_subscription_ref(message.from_user.id, parts[2])
                if not sub:
                    await message.answer(t(message.from_user.id, "no_subs"))
                    return
                sub_id = sub[0]

                update_args = {}
                kv = _parse_kv_floats(message.text or "")
                if 'min' in kv:
                    update_args['min_price'] = kv['min']
                if 'max' in kv:
                    update_args['max_price'] = kv['max']
                if 'percent' in kv:
                    update_args['notify_percent'] = kv['percent']

                if update_args:
                    update_subscription_settings(sub_id, **update_args)
                    await message.answer(t(message.from_user.id, "price_alerts_updated"))
                    return

            await message.answer(t(message.from_user.id, "price_alerts_usage"))

        elif subcmd == "interval":
            if len(parts) == 4 and parts[2].isdigit() and parts[3].isdigit():
                sub, _public_number = resolve_user_subscription_ref(message.from_user.id, parts[2])
                if not sub:
                    await message.answer(t(message.from_user.id, "no_subs"))
                    return
                sub_id = sub[0]
                minutes = int(parts[3])

                if minutes < 15:
                    await message.answer(t(message.from_user.id, "interval_too_short"))
                    return

                update_subscription_settings(sub_id, notify_interval=minutes)
                await message.answer(
                    t(message.from_user.id, "interval_set").format(minutes=minutes)
                )
                return

            await message.answer(t(message.from_user.id, "interval_usage"))

        else:
            await message.answer(t(message.from_user.id, "settings_usage"))

    except Exception as e:
        logger.exception("Settings command error: %s", e)
        await message.answer(t(message.from_user.id, "error_generic"))


@router.message(Command("runcheck"))
async def cmd_runcheck(message: types.Message):
    """Run full subscription check manually (admin-only)."""
    user_id = message.from_user.id
    if not is_admin(user_id):
        await message.answer(t(user_id, "admin_access_denied"))
        return

    await message.answer(t(user_id, "please_wait"))
    try:
        result = await check_all(trigger=f"manual:{user_id}")
        if result.get("status") == "skipped":
            await message.answer("⏳ Проверка уже выполняется. Повторите позже.")
            return
        if result.get("status") == "failed":
            await message.answer(t(user_id, "error_runcheck"))
            return
        await message.answer(
            "✅ " + t(user_id, "done") +
            f"\nProcessed: {result.get('processed', 0)}, alerted: {result.get('alerted', 0)}"
        )
    except Exception as e:
        logger.exception("manual runcheck error: %s", e)
        await message.answer(t(user_id, "error_runcheck") + f": {e}")





async def cmd_stats_old(message: types.Message):
    """Show price statistics for a subscription"""
    try:
        args = message.text.split()
        if len(args) < 2:
            await message.answer(t(message.from_user.id, "cmd_stats_usage"))
            return

        sub, public_number = resolve_user_subscription_ref(message.from_user.id, args[1])

        if not sub:
            await message.answer(t(message.from_user.id, "no_subs_found_id"))
            return
        sub_id = sub[0]
        label = f"№ {public_number}" if public_number is not None else f"ID {sub_id}"

        stats = get_price_stats(sub_id)

        if stats['count'] == 0:
            await message.answer(t(message.from_user.id, "stats_no_history"))
            return


        curr = f"{stats['current']:.2f}" if stats['current'] else "—"
        min_p = f"{stats['min']:.2f}" if stats['min'] else "—"
        max_p = f"{stats['max']:.2f}" if stats['max'] else "—"
        avg_p = f"{stats['avg']:.2f}" if stats['avg'] else "—"


        header = t(message.from_user.id, "stats_header")
        text = f"""{header}

🏷️ {label}
🔗 {sub[2][:50]}...

💰 {t(message.from_user.id, 'current_price')}: {curr} TL
📉 {t(message.from_user.id, 'min_price')}: {min_p} TL
📈 {t(message.from_user.id, 'max_price')}: {max_p} TL
📊 {t(message.from_user.id, 'avg_price')}: {avg_p} TL
📈 {t(message.from_user.id, 'trend')}: {stats['trend']}
📅 {t(message.from_user.id, 'days_data')}: {stats['days']}
📌 {t(message.from_user.id, 'points')}: {stats['count']}
"""
        await message.answer(text, parse_mode="Markdown")

    except ValueError:
        await message.answer(t(message.from_user.id, "provide_subscription_id"))
    except Exception as e:
        logger.exception("Stats command error: %s", e)
        await message.answer(t(message.from_user.id, "error_generic"))



async def cmd_all_list_old(message: types.Message):
    """Show all subscriptions in compact table format"""
    try:
        subs = get_user_subscriptions(message.from_user.id)

        if not subs:
            await message.answer(t(message.from_user.id, "no_subs"))
            return


        header = t(message.from_user.id, "cmd_all_list_header") + "\n\n"
        header += "`№   | " + t(message.from_user.id, "mode") + "      | " + t(message.from_user.id, "price") + "    | " + t(message.from_user.id, "status") + "`\n"
        header += "`" + "—" * 38 + "`\n"

        rows = []
        for index, sub in enumerate(subs, start=1):
            try:
                (sub_id, user_id, url, mode, last_price, product_title, product_image,
                 min_price, max_price, notify_percent, notify_interval, last_notify_time, price_alert) = sub
            except ValueError:
                (sub_id, user_id, url, mode, last_price, product_title, product_image,
                 min_price, max_price, notify_percent, notify_interval, last_notify_time) = sub[:12]
                price_alert = None

            mode_short = "⏰" if mode == "hourly" else "💸" if mode == "discount" else "❓"
            price_str = f"{last_price:.0f}" if last_price else "—"
            alert_status = "🎯" if price_alert else " "

            row = f"`{index:3d} | {mode_short} {mode:8s} | {price_str:6s} | {alert_status}`"
            rows.append(row)

        text = header + "\n".join(rows)
        text += f"\n\n✅ {t(message.from_user.id, 'total')}: {len(subs)} {t(message.from_user.id, 'subscriptions')}"

        await message.answer(text, parse_mode="Markdown")

    except Exception as e:
        logger.exception("All list command error: %s", e)
        await message.answer(t(message.from_user.id, "error_generic"))



async def cmd_top_drops_old(message: types.Message):
    """Show top products with biggest price drops"""
    try:
        from database import get_top_price_drops

        drops = get_top_price_drops(message.from_user.id, limit=10)

        if not drops:
            await message.answer(t(message.from_user.id, "top_drops_no_data"))
            return

        text = t(message.from_user.id, "cmd_top_drops_header") + "\n\n"

        for i, (sub_id, url, title, curr_price, min_price, drop_pct) in enumerate(drops, 1):
            title_short = (title or t(message.from_user.id, "product"))[:30]
            icon = "🔴" if drop_pct < 0 else "🟢"
            curr_str = f"{curr_price:.0f}" if curr_price else "—"
            min_str = f"{min_price:.0f}" if min_price else "—"

            number = get_user_subscription_number(message.from_user.id, sub_id)
            label = f"№ {number}" if number is not None else f"ID {sub_id}"
            text += f"{i}. {icon} *{drop_pct:+.1f}%* | {label}\n"
            text += f"   {title_short}\n"
            text += f"   {t(message.from_user.id, 'current_price')}: {curr_str} TL | {t(message.from_user.id, 'min_price_label')}: {min_str} TL\n\n"

        await message.answer(text, parse_mode="Markdown")

    except Exception as e:
        logger.exception("Top drops command error: %s", e)
        await message.answer(t(message.from_user.id, "error_generic"))



@router.message(Command("export"))
async def cmd_export(message: types.Message):
    try:
        parts = (message.text or "").split()
        fmt = "csv"
        if len(parts) > 1 and parts[1].lower() in {"csv", "json"}:
            fmt = parts[1].lower()

        user_id = message.from_user.id
        subs = export_user_subscriptions(user_id)
        if not subs:
            await message.answer(t(user_id, "no_subs"))
            return

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        os.makedirs("backups", exist_ok=True)

        if fmt == "json":
            fname = f"backups/subscriptions_{user_id}_{ts}.json"
            payload = json.dumps(subs, ensure_ascii=False, indent=2)
            with open(fname, "w", encoding="utf-8") as f:
                f.write(payload)

            with open(fname, "rb") as f:
                await bot.send_document(user_id, types.InputFile(f, filename=os.path.basename(fname)))
            await message.answer(t(user_id, "export_done").format(path=fname))
            return


        fname = f"backups/subscriptions_{user_id}_{ts}.csv"

        cols = [
            'id','user_id','url','mode','last_price','product_title','product_image',
            'min_price','max_price','notify_percent','notify_interval','last_notify_time','price_alert','tags'
        ]

        with open(fname, "w", encoding="utf-8-sig", newline='') as f:
            writer = csv.DictWriter(f, fieldnames=cols)
            writer.writeheader()
            for row in subs:

                safe_row = {k: row.get(k, "") for k in cols}
                writer.writerow(safe_row)

        with open(fname, "rb") as f:
            await bot.send_document(user_id, types.InputFile(f, filename=os.path.basename(fname)))

        await message.answer(t(user_id, "export_done").format(path=fname))

    except Exception as e:
        logger.exception("Export command error: %s", e)
        await message.answer(t(message.from_user.id, "error_generic"))



@router.message(Command("history_export"))
async def cmd_history_export(message: types.Message):
    try:
        parts = (message.text or "").split()
        if len(parts) < 2 or not parts[1].isdigit():
            await message.answer(t(message.from_user.id, "history_export_usage"))
            return

        sub, _public_number = resolve_user_subscription_ref(message.from_user.id, parts[1])
        if not sub:
            await message.answer(t(message.from_user.id, "no_subs"))
            return
        sub_id = sub[0]
        fmt = "csv"
        days = None

        for p in parts[2:]:
            if p.lower() in {"csv", "json"}:
                fmt = p.lower()
            elif p.isdigit():
                days = int(p)

        if days is not None:
            rows = get_local_price_history(sub_id, days=min(days, 365))
        else:
            rows = get_price_history(sub_id, limit=5000)

        if not rows:
            await message.answer(t(message.from_user.id, "history_export_no_data"))
            return

        os.makedirs("backups", exist_ok=True)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')


        if fmt == "json":
            if isinstance(rows[0][0], str):
                payload = json.dumps([{"iso": r[0], "price": r[1]} for r in rows], ensure_ascii=False, indent=2)
            else:
                payload = json.dumps([{"ts": r[0], "price": r[1]} for r in rows], ensure_ascii=False, indent=2)
            fname = f"backups/history_{sub_id}_{ts}.json"
            with open(fname, "w", encoding="utf-8") as f:
                f.write(payload)
            with open(fname, "rb") as f:
                await bot.send_document(message.from_user.id, types.InputFile(f, filename=os.path.basename(fname)))
            await message.answer(t(message.from_user.id, "history_export_ready").format(filename=fname))
            return


        fname = f"backups/history_{sub_id}_{ts}.csv"
        with open(fname, "w", encoding="utf-8-sig", newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["ts", "iso_datetime", "price"])
            for ts_val, price in rows:
                if isinstance(ts_val, str):
                    iso = ts_val
                    raw_ts = ""
                else:
                    try:
                        iso = datetime.utcfromtimestamp(int(ts_val)).isoformat()
                    except Exception:
                        iso = ""
                    raw_ts = ts_val
                writer.writerow([raw_ts, iso, price])

        with open(fname, "rb") as f:
            await bot.send_document(message.from_user.id, types.InputFile(f, filename=os.path.basename(fname)))

        await message.answer(t(message.from_user.id, "history_export_ready").format(filename=fname))

    except Exception as e:
        logger.exception("history_export error: %s", e)
        await message.answer(t(message.from_user.id, "error_generic"))



@router.message(Command("history_plot"))
async def cmd_history_plot(message: types.Message):
    status_message = None
    try:
        parts = (message.text or "").split()
        if len(parts) < 2 or not parts[1].isdigit():
            await message.answer(t(message.from_user.id, "history_plot_usage"))
            return

        sub, _public_number = resolve_user_subscription_ref(message.from_user.id, parts[1])
        if not sub:
            await message.answer(t(message.from_user.id, "no_subs"))
            return
        sub_id = sub[0]
        days = None
        if len(parts) > 2 and parts[2].isdigit():
            days = int(parts[2])

        if days is not None:
            rows = get_local_price_history(sub_id, days=min(days, 180))
        else:
            rows = get_price_history(sub_id, limit=2000)

        if not rows:
            await message.answer(t(message.from_user.id, "history_plot_no_data"))
            return

        status_message = await _send_progress_message(
            message,
            t(message.from_user.id, "status_loading_history"),
        )

        hist = []
        for ts_val, price in rows:
            if isinstance(ts_val, str):
                hist.append((ts_val, price))
            else:
                try:
                    iso = datetime.utcfromtimestamp(int(ts_val)).isoformat()
                except Exception:
                    iso = str(ts_val)
                hist.append((iso, price))

        url = sub[2] if len(sub) > 2 else ""
        await send_history_plot(message.from_user.id, url, hist)
        await _clear_progress_message(status_message)

    except Exception as e:
        logger.exception("history_plot error: %s", e)
        if status_message is not None:
            await _replace_progress_message(
                status_message,
                t(message.from_user.id, "error_generic"),
                fallback_target=message,
            )
        else:
            await message.answer(t(message.from_user.id, "error_generic"))



@router.message(Command("compare"))
async def cmd_compare(message: types.Message):
    """Unified compare command:
    - /compare <subscription_id>
    - /compare <url1> <url2>
    """
    user_id = message.from_user.id
    add_user_if_not_exists(user_id)
    args = (message.text or "").split()
    status_message = None

    try:

        if len(args) == 2 and args[1].isdigit():
            from scraper import get_similar_products_comparison

            sub, _public_number = resolve_user_subscription_ref(user_id, args[1])

            if not sub:
                await message.answer(t(user_id, "no_subs_found_id"))
                return
            sub_id = sub[0]

            status_message = await _send_progress_message(
                message,
                t(user_id, "status_loading_compare"),
            )
            comparison = await get_similar_products_comparison(user_id, sub_id)
            if comparison:
                await _replace_progress_message(
                    status_message,
                    comparison,
                    fallback_target=message,
                    parse_mode="Markdown",
                )
            else:
                await _replace_progress_message(
                    status_message,
                    t(user_id, "compare_no_similar"),
                    fallback_target=message,
                )
            return


        if len(args) >= 3:
            await _compare_products_by_urls(message, args[1], args[2])
            return

        await message.answer(
            f"📊 <b>{t(user_id, 'cmd_compare_usage')}</b>\n\n"
            "Примеры:\n"
            "<code>/compare 1</code>\n"
            "<code>/compare https://trendyol.com/product1 https://trendyol.com/product2</code>",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.exception("compare command error: %s", e)
        if status_message is not None:
            await _replace_progress_message(
                status_message,
                t(user_id, "error_generic"),
                fallback_target=message,
            )
        else:
            await message.answer(t(user_id, "error_generic"))


async def _compare_products_by_urls(message: types.Message, url1: str, url2: str) -> None:
    """Compare prices for two direct product URLs."""
    user_id = message.from_user.id

    if not (is_trendyol_product_url(url1) and is_trendyol_product_url(url2)):
        await message.answer(t(user_id, "not_product_url"))
        return

    status_message = await _send_progress_message(
        message,
        t(user_id, "status_loading_compare"),
    )

    try:

        (price1, title1, _), (price2, title2, _) = await asyncio.gather(
            get_product_info_async(url1),
            get_product_info_async(url2),
        )

        if price1 is None or price2 is None:
            await _replace_progress_message(
                status_message,
                t(user_id, "compare_error_no_price"),
                fallback_target=message,
            )
            return

        comparison_text = f"""
📊 <b>СРАВНЕНИЕ ТОВАРОВ</b>

🏷️ <b>Товар 1:</b>
{title1 or url1}
💰 Цена: {price1:.2f} TL

🏷️ <b>Товар 2:</b>
{title2 or url2}
💰 Цена: {price2:.2f} TL

📈 <b>Разница:</b> {abs(price1 - price2):.2f} TL ({abs(price1 - price2) / max(price1, price2) * 100:.1f}%)

{'🟢 Товар 1 дешевле' if price1 < price2 else '🟢 Товар 2 дешевле' if price2 < price1 else '⚪ Цены равны'}
"""
        await _replace_progress_message(
            status_message,
            comparison_text,
            fallback_target=message,
            parse_mode="HTML",
        )
    except Exception as e:
        logger.exception("Error in URL compare command: %s", e)
        await _replace_progress_message(
            status_message,
            t(user_id, "error_generic"),
            fallback_target=message,
        )




def _filter_subscribe_button(message: types.Message) -> bool:
    """Filter for subscribe button and related keywords"""
    if not message.text or not message.from_user:
        return False
    user_id = message.from_user.id
    subscribe_btn = t(user_id, "btn_subscribe")
    subs_btn = t(user_id, "btn_subs")
    text_lower = message.text.lower()
    return (
        subscribe_btn == message.text
        or (
            ("подпис" in text_lower)
            and ("мои" not in text_lower)
            and ("мои подпис" not in text_lower)
            and (message.text != subs_btn)
        )
    )

@router.message(_filter_subscribe_button)
async def cmd_subscribe_ui(message: types.Message):
    await message.answer(t(message.from_user.id, "send_link_prompt"))


async def handle_url_old(message: types.Message):
    user_id = message.from_user.id
    status_message = None
    try:
        raw = (message.text or "").strip()


        if not raw or len(raw) < 10:
            await message.answer(t(user_id, "invalid_url"))
            return

        url = await resolve_short_url(raw)
        url = normalize_url(url)
        url_lower = url.lower()

        if "trendyol.com" not in url_lower and "ty.gl/" not in url_lower:
            await message.answer(t(user_id, "not_trendyol"))
            return

        if not is_trendyol_product_url(url):
            await message.answer(t(user_id, "not_product_url"))
            return

        add_user_if_not_exists(user_id)


        subs = get_user_subscriptions(user_id)
        for index, sub in enumerate(subs, start=1):
            try:
                (sid, _sub_user_id, u, mode, last_price, product_title, product_image,
                 min_price, max_price, notify_percent, notify_interval, last_notify_time, price_alert) = sub
            except ValueError:

                (sid, _sub_user_id, u, mode, last_price, product_title, product_image,
                 min_price, max_price, notify_percent, notify_interval, last_notify_time) = sub[:12]
            if normalize_url(u).lower() == url_lower:
                await message.answer(t(user_id, "already_subscribed"))
                return

        status_message = await _send_progress_message(
            message,
            t(user_id, "status_checking_product"),
        )

        sub_id = add_subscription(user_id, url, DEFAULT_NOTIFY_MODE)

        try:
            price, title, image = await get_product_info_async(url)
        except asyncio.TimeoutError:
            logger.warning("Timeout fetching product info for subscription: %s", url)
            price, title, image = None, None, None
        except aiohttp.ClientError as e:
            logger.warning("Network error fetching product info for subscription %s: %s", url, e)
            price, title, image = None, None, None
        except Exception as e:
            logger.exception("Unexpected error fetching product info for subscription: %s", e)
            price, title, image = None, None, None


        try:
            if title or image:
                update_subscription_meta(sub_id, title, image)
        except sqlite3.DatabaseError as e:
            logger.error("Database error updating subscription meta for %s: %s", sub_id, e)
        except Exception as e:
            logger.exception("Unexpected error updating subscription meta for %s: %s", sub_id, e)

        if price is not None:
            try:
                update_last_price(sub_id, price)
                await send_subscription_added_message(
                    message,
                    user_id,
                    sub_id,
                    url,
                    title,
                    price,
                    image,
                    DEFAULT_NOTIFY_MODE,
                )
            except Exception:
                await message.answer(
                    t(user_id, "subscribed"),
                    reply_markup=subscription_controls_kb_for_user(user_id, sub_id)
                )
        else:
            await send_subscription_added_message(
                message,
                user_id,
                sub_id,
                url,
                title,
                None,
                image,
                DEFAULT_NOTIFY_MODE,
            )
        await _clear_progress_message(status_message)

    except Exception as e:
        logger.exception("Error in handle_url for user %s: %s", user_id, e)
        if status_message is not None:
            await _replace_progress_message(status_message, t(user_id, "error_generic"), fallback_target=message)
        else:
            await message.answer(t(user_id, "error_generic"))


handle_url = handle_url_old


def _filter_alert_price(message: types.Message) -> bool:
    """Filter for alert price input"""
    if not message.from_user or not message.text:
        return False
    return message.from_user.id in alert_edit_state and not message.text.startswith("/")

@router.message(_filter_alert_price)
async def handle_alert_price(message: types.Message):
    """Handle user input for setting alert price"""
    user_id = message.from_user.id
    sub_id = alert_edit_state.get(user_id)

    if not sub_id:
        return

    try:

        price_text = message.text.strip().replace(' ', '').replace('TL', '').replace('₺', '')
        target_price = float(price_text)

        if target_price <= 0:
            await message.answer(t(user_id, "price_alert_price_negative"))
            return


        sub = get_subscription(sub_id)
        if not sub or sub[1] != user_id:
            await message.answer(t(user_id, "error_not_your_sub"))
            del alert_edit_state[user_id]
            return


        update_subscription_settings(sub_id, price_alert=target_price)

        title = sub[5] if len(sub) > 5 and sub[5] else sub[2][:50] + "..."
        await message.answer(
            t(user_id, "price_alert_set_success").format(price=target_price) +
            f"\n\n📦 {title}",
            reply_markup=get_main_kb(user_id)
        )

        del alert_edit_state[user_id]

    except ValueError:
        await message.answer(t(user_id, "price_alert_price_must_be_number"))
    except Exception as e:
        logger.exception("Error setting alert price: %s", e)
        await message.answer(t(user_id, "error_generic"))
        if user_id in alert_edit_state:
            del alert_edit_state[user_id]


def _filter_report_text(message: types.Message) -> bool:
    """Filter for report text input"""
    if not message.from_user or not message.text:
        return False
    return message.from_user.id in report_state and not message.text.startswith("/")

@router.message(_filter_report_text)
async def handle_report_text(message: types.Message):
    """Handle user input for report text"""
    user_id = message.from_user.id
    state_data = report_state.get(user_id)

    if not state_data or state_data.get("step") != "waiting_text":
        return

    report_text = message.text.strip()
    if len(report_text) < 5:
        await message.answer(t(user_id, "report_too_short"))
        return

    await submit_user_report(user_id, report_text, message)
    del report_state[user_id]


async def _filter_mysubs(message: types.Message) -> bool:
    """Filter for /mysubs button and similar"""
    if not message.text:
        return False
    try:
        user_id = message.from_user.id if message.from_user else 0
        return (t(user_id, "btn_subs") == message.text or "мои подпис" in message.text.lower())
    except Exception as e:
        logger.exception("_filter_mysubs error: %s", e)
        return False

@router.message(_filter_mysubs)
async def cmd_mysubs(message: types.Message):
    user_id = message.from_user.id
    subs = get_user_subscriptions(user_id)
    if not subs:
        await message.answer(t(user_id, "no_subs"))
        return

    try:
        overview_text, overview_keyboard = build_subscriptions_overview(user_id, subs)
        await message.answer(
            overview_text,
            reply_markup=overview_keyboard,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except Exception as e:
        logger.exception("Error sending mysubs overview for user %s: %s", user_id, e)
        await message.answer(t(user_id, "error_generic"))


async def _filter_recommend(message: types.Message) -> bool:
    """Filter for recommend button"""
    if not message.text:
        return False
    try:
        user_id = message.from_user.id if message.from_user else 0
        return message.text == t(user_id, "btn_recommend")
    except Exception as e:
        logger.exception("_filter_recommend error: %s", e)
        return False

@router.message(_filter_recommend)
async def cmd_recommend_button(message: types.Message):
    """Обработчик кнопки рекомендаций в меню"""
    await cmd_recommend(message)

async def _filter_trending(message: types.Message) -> bool:
    """Filter for trending button"""
    if not message.text:
        return False
    try:
        user_id = message.from_user.id if message.from_user else 0
        return (t(user_id, "btn_trending") == message.text or "тренд" in message.text.lower() or "трен" in message.text.lower())
    except Exception as e:
        logger.exception("_filter_trending error: %s", e)
        return False

@router.message(_filter_trending)
async def cmd_trending(message: types.Message):
    await message.answer(t(message.from_user.id, "trending_header"), reply_markup=trending_menu_kb(message.from_user.id))


async def _filter_trending_search(message: types.Message) -> bool:
    """Filter for trending search text input"""
    if not message.text or message.text.startswith("/"):
        return False
    if not message.from_user or message.from_user.id not in TREND_SEARCH_AWAIT:
        return False
    return True

@router.message(_filter_trending_search)
async def trending_search_text(message: types.Message):
    user_id = message.from_user.id
    q = (message.text or "").strip()
    if not q:
        await message.answer(t(user_id, "trending_enter_query"))
        return

    if user_id in TREND_SEARCH_AWAIT:
        TREND_SEARCH_AWAIT.remove(user_id)
    status_message = None
    try:
        status_message = await _send_progress_message(
            message,
            t(user_id, "status_loading_trends"),
        )
        items = await get_trending_by_search_top3_async(q)
        if not items:
            await _replace_progress_message(
                status_message,
                t(user_id, "trending_no_results"),
                fallback_target=message,
            )
            return
        await _replace_progress_message(
            status_message,
            t(user_id, "trending_header") + "\n\n" + format_trending_items(user_id, items),
            fallback_target=message,
        )
    except Exception as e:
        logger.exception("trending search error: %s", e)
        await _replace_progress_message(
            status_message,
            t(user_id, "trending_no_results"),
            fallback_target=message,
        )


def _filter_unsubscribe(message: types.Message) -> bool:
    if not message.text or not message.from_user:
        return False
    user_id = message.from_user.id
    unsubscribe_btn = t(user_id, "btn_unsubscribe")
    return unsubscribe_btn == message.text or "отпис" in message.text.lower()


@router.message(_filter_unsubscribe)
async def cmd_unsubscribe_all(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅", callback_data="confirm_unsub_all:yes"),
        InlineKeyboardButton(text="🚫", callback_data="confirm_unsub_all:no"),
    ]])
    await message.answer(t(message.from_user.id, "btn_unsubscribe") + " ❓", reply_markup=kb)


scheduler = AsyncIOScheduler()


async def send_grouped_notifications(grouped_notifications: Dict[int, List[NotificationItem]]) -> None:
    """Send price notifications grouped by user."""

    async with scheduler_lock:
        for user_id, notifications in grouped_notifications.items():
            try:
                if len(notifications) == 1:
                    text, image, reply_markup, parse_mode = _notification_delivery_parts(notifications[0])
                    await send_notification_with_timeout(
                        user_id,
                        text,
                        image,
                        timeout=15.0,
                        parse_mode=parse_mode,
                        reply_markup=reply_markup,
                    )
                    action_event("NOTIFY", "sent price notification", user=user_id, count=1)
                else:
                    grouped_text = (
                        f"🔔 <b>{html.escape(t(user_id, 'notifications_group_title'))}</b> "
                        f"({len(notifications)})\n\n"
                    )

                    for i, notification in enumerate(notifications[:10], 1):
                        grouped_text += f"{i}. {_notification_summary_html(notification)}\n\n"

                    if len(notifications) > 10:
                        grouped_text += html.escape(
                            t(user_id, "notifications_more").format(count=len(notifications) - 10)
                        )

                    await send_notification_with_timeout(
                        user_id,
                        grouped_text,
                        image=None,
                        timeout=15.0,
                        parse_mode="HTML",
                        reply_markup=_grouped_notifications_keyboard(user_id),
                    )
                    action_event("NOTIFY", "sent grouped price notifications", user=user_id, count=len(notifications))

            except Exception as e:
                logger.exception("Error sending grouped notifications to user %s: %s", user_id, e)


async def _check_all_impl(trigger: str = "scheduler") -> Dict[str, Any]:
    logger.info("Scheduler job: checking subscriptions (trigger=%s)", trigger)
    total = get_subscriptions_count()
    logger.info("Found %d subscriptions to check", total)
    action_event("JOB", "price check started", trigger=trigger, subscriptions=total)

    task_batch_size = _get_env_int(
        "CHECK_ALL_TASK_BATCH_SIZE",
        200,
        min_value=1,
        max_value=5000,
    )
    db_batch_size = _get_env_int(
        "CHECK_ALL_DB_BATCH_SIZE",
        1000,
        min_value=task_batch_size,
        max_value=50000,
    )


    user_settings_cache = {}

    def get_cached_user_settings(user_id: int):
        """Возвращает настройки пользователя из кэша или БД."""
        if user_id not in user_settings_cache:
            user_settings_cache[user_id] = get_user_settings(user_id)
        return user_settings_cache[user_id]

    sem = asyncio.Semaphore(CHECK_ALL_FETCH_CONCURRENCY)
    processed_count = 0
    alerted_count = 0


    price_points_batch = []


    grouped_notifications = {}

    async def process(sub):
        nonlocal processed_count, alerted_count

        try:
            (sub_id, user_id, url, mode, last_price, product_title, product_image,
             min_price, max_price, notify_percent, notify_interval, last_notify_time, price_alert) = sub
        except ValueError:

            (sub_id, user_id, url, mode, last_price, product_title, product_image,
             min_price, max_price, notify_percent, notify_interval, last_notify_time) = sub[:12]
            price_alert = None

        async with sem:
            try:

                current_hour = datetime.now().hour
                lang, quiet_start, quiet_end = get_cached_user_settings(user_id)

                is_quiet_time = False
                if quiet_start <= quiet_end:
                    is_quiet_time = quiet_start <= current_hour < quiet_end
                else:
                    is_quiet_time = current_hour >= quiet_start or current_hour < quiet_end

                if is_quiet_time:
                    logger.debug(f"Quiet hours for user {user_id} ({current_hour}:00)")
                    return


                current_time = int(time.time())
                if last_notify_time and notify_interval:
                    if current_time - last_notify_time < notify_interval * 60:
                        return


                try:
                    price, title, image = await get_product_info_async(url)
                except asyncio.TimeoutError:
                    logger.warning("Timeout fetching product info for sub %s", sub_id)
                    return
                except aiohttp.ClientError as e:
                    logger.warning("Network error fetching product info for sub %s: %s", sub_id, e)
                    return
                except Exception as e:
                    logger.exception("Unexpected error fetching product info for sub %s: %s", sub_id, e)
                    return


                if not title and product_title:
                    title = product_title
                if not image and product_image:
                    image = product_image

                if price is None:
                    logger.info("Price not found for sub %s url %s", sub_id, url)
                    return

                processed_count += 1

                if last_price is None:
                    update_last_price(sub_id, price)
                    try:

                        add_price_point(sub_id, url, float(price), source='collector')
                    except Exception:
                        logger.exception("Failed to add initial price point for sub %s", sub_id)
                    logger.debug("Set initial last_price for sub %s -> %s", sub_id, price)
                    return


                notification_needed = False
                notification_details: Optional[Dict[str, Any]] = None

                change_percent = None
                try:
                    if float(last_price) != 0:
                        change_percent = ((float(price) - float(last_price)) / float(last_price)) * 100
                except (TypeError, ValueError, ZeroDivisionError):
                    change_percent = None


                if price_alert is not None and price <= price_alert:
                    notification_needed = True
                    notification_details = {
                        "reason": "target_hit",
                        "old_price": last_price if price != last_price else None,
                        "percent": change_percent,
                        "target_price": price_alert,
                    }
                    update_subscription_settings(sub_id, price_alert=None)

                elif mode == "hourly":
                    notification_needed = True
                    notification_details = {
                        "reason": "hourly",
                    }

                elif mode == "discount":
                    price_changed_percent = abs(change_percent) if change_percent is not None else 0

                    if notify_percent and abs(price_changed_percent) >= notify_percent:
                        notification_needed = True
                        if price < last_price:
                            notification_details = {
                                "reason": "percent_drop",
                                "old_price": last_price,
                                "percent": change_percent,
                            }
                        else:
                            notification_details = {
                                "reason": "percent_increase",
                                "old_price": last_price,
                                "percent": change_percent,
                            }
                    elif price < last_price:
                        notification_needed = True
                        notification_details = {
                            "reason": "discount_drop",
                            "old_price": last_price,
                            "percent": change_percent,
                        }


                if min_price is not None and price < min_price and (
                    not notification_details or notification_details.get("reason") != "target_hit"
                ):
                    notification_needed = True
                    notification_details = {
                        "reason": "below_min",
                        "old_price": last_price if price != last_price else None,
                        "percent": change_percent,
                        "min_price": min_price,
                    }
                elif max_price is not None and price > max_price and (
                    not notification_details or notification_details.get("reason") != "target_hit"
                ):
                    notification_needed = True
                    notification_details = {
                        "reason": "above_max",
                        "old_price": last_price if price != last_price else None,
                        "percent": change_percent,
                        "max_price": max_price,
                    }

                if notification_needed and notification_details:
                    action_event(
                        "PRICE",
                        "notification queued",
                        user=user_id,
                        sub_id=sub_id,
                        reason=notification_details.get("reason"),
                        old_price=last_price,
                        new_price=price,
                        title=short_value(title or product_title or "unknown", 60),
                    )

                    if user_id not in grouped_notifications:
                        grouped_notifications[user_id] = []
                    grouped_notifications[user_id].append(
                        build_price_notification_payload(
                            user_id,
                            sub_id=sub_id,
                            url=url,
                            title=title,
                            image=image,
                            current_price=price,
                            **notification_details,
                        )
                    )

                    alerted_count += 1
                    update_notify_time(sub_id)


                if price != last_price:

                    try:
                        last_point = get_last_price_point(sub_id)
                        should_insert = True
                        if last_point:
                            last_ts, last_p = last_point

                            if float(last_p) == float(price) and int(time.time()) - int(last_ts) < 3600:
                                should_insert = False
                        if should_insert:


                            price_points_batch.append((sub_id, float(price), int(time.time()), url))
                            logger.info(f"Collected price point for batch: sub={sub_id}, price={price}")
                    except Exception:
                        logger.exception("Failed to store price point for sub %s", sub_id)

                    update_last_price(sub_id, price)

            except Exception as e:
                sid = locals().get('sub_id', 'unknown')
                logger.exception("check_all inner error for sub %s: %s", sid, e)

    current_batch = []
    for sub in iter_all_subscriptions(batch_size=db_batch_size):
        current_batch.append(sub)
        if len(current_batch) >= task_batch_size:
            await asyncio.gather(*(process(s) for s in current_batch))
            current_batch.clear()

    if current_batch:
        await asyncio.gather(*(process(s) for s in current_batch))


    if price_points_batch:
        try:
            await asyncio.to_thread(save_price_points_batch, price_points_batch)
            logger.info("Batch saved %d price points", len(price_points_batch))
        except Exception as e:
            logger.exception("Failed to batch save price points: %s", e)

            for sub_id, price, ts, url in price_points_batch:
                try:
                    save_price_point(sub_id, price, ts)
                except Exception as fallback_e:
                    logger.error("Fallback save failed for sub %s: %s", sub_id, fallback_e)


    await send_grouped_notifications(grouped_notifications)

    logger.info(
        "Scheduler job finished (trigger=%s) — processed %d, alerted %d",
        trigger,
        processed_count,
        alerted_count,
    )
    return {
        "status": "completed",
        "trigger": trigger,
        "total": total,
        "processed": processed_count,
        "alerted": alerted_count,
    }


async def check_all(trigger: str = "scheduler") -> Dict[str, Any]:
    """Run price checks with a concurrency guard to prevent overlapping runs."""
    if check_all_lock.locked():
        logger.warning("check_all skipped: already running (trigger=%s)", trigger)
        action_event("JOB", "price check skipped", trigger=trigger, reason="already_running")
        return {"status": "skipped", "trigger": trigger, "reason": "already_running"}

    async with check_all_lock:
        started_at = time.time()
        try:
            result = await _check_all_impl(trigger=trigger)
            result["duration_sec"] = round(time.time() - started_at, 2)
            action_event(
                "JOB",
                "price check finished",
                trigger=trigger,
                total=result.get("total"),
                processed=result.get("processed"),
                alerted=result.get("alerted"),
                duration=f"{result['duration_sec']}s",
            )
            return result
        except Exception as e:
            logger.exception("check_all failed (trigger=%s): %s", trigger, e)
            return {
                "status": "failed",
                "trigger": trigger,
                "reason": str(e),
                "duration_sec": round(time.time() - started_at, 2),
            }

async def start_scheduler_async(delay: float = 1.0):
    """Асинхронно стартует планировщик после того, как event loop запущен.
    Настраиваем AsyncIOScheduler на текущий running loop и добавляем корутину
    `check_all` как задачу-джобу, чтобы APScheduler вызывал её внутри event loop.
    """
    if delay > 0:
        await asyncio.sleep(delay)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.exception("No running event loop, cannot start scheduler")
        return

    async with scheduler_start_lock:
        if getattr(scheduler, "running", False):
            logger.info("Scheduler already running; skip duplicate start")
            return


        try:
            scheduler.configure(event_loop=loop)
        except Exception:

            logger.debug("scheduler.configure(event_loop=loop) failed or not needed", exc_info=True)


        try:
            scheduler.add_job(
                check_all,
                "interval",
                id=CHECK_ALL_JOB_ID,
                minutes=CHECK_ALL_INTERVAL_MINUTES,
                next_run_time=datetime.now(),
                replace_existing=True,
                max_instances=1,
                coalesce=True,
                misfire_grace_time=max(60, CHECK_ALL_INTERVAL_MINUTES * 60),
            )
            scheduler.add_job(
                backup_database,
                "cron",
                id=BACKUP_JOB_ID,
                hour=DB_BACKUP_HOUR,
                minute=DB_BACKUP_MINUTE,
                replace_existing=True,
                max_instances=1,
                coalesce=True,
                misfire_grace_time=3600,
            )
            scheduler.start()
            logger.info(
                "Scheduler started (async): check interval=%s min, backup=%02d:%02d, keep=%d",
                CHECK_ALL_INTERVAL_MINUTES,
                DB_BACKUP_HOUR,
                DB_BACKUP_MINUTE,
                DB_BACKUP_KEEP_FILES,
            )
            action_event(
                "START",
                "scheduler started",
                check_interval_min=CHECK_ALL_INTERVAL_MINUTES,
                backup_time=f"{DB_BACKUP_HOUR:02d}:{DB_BACKUP_MINUTE:02d}",
                keep_backups=DB_BACKUP_KEEP_FILES,
            )
        except Exception:
            logger.exception("Failed to start scheduler or add job")


def analyze_user_preferences(user_id: int) -> Dict[str, Any]:
    """Analyze user's product preferences based on subscriptions"""
    try:
        from database import get_connection

        with get_connection() as conn:
            cursor = conn.cursor()


            cursor.execute("""
                SELECT url, product_title
                FROM subscriptions
                WHERE user_id = ?
            """, (user_id,))

            subscriptions = cursor.fetchall()

            if not subscriptions:
                return {"categories": [], "brands": [], "has_subscriptions": False}

            categories = []
            brands = []
            keywords = []

            for url, title in subscriptions:

                url_parts = url.replace('https://www.trendyol.com/', '').split('/')
                if len(url_parts) > 0:
                    brand = url_parts[0].lower()
                    if brand and not brand.startswith('p-'):
                        brands.append(brand)


                if title:

                    title_lower = title.lower()


                    if any(word in title_lower for word in ['telefon', 'iphone', 'samsung', 'xiaomi', 'huawei', 'oppo', 'vivo', 'realme']):
                        categories.append('smartphones')
                        keywords.extend(['telefon', 'smartphone', 'mobile', 'android', 'ios'])

                        if 'iphone' in title_lower or 'apple' in title_lower:
                            brands.append('apple')
                        elif 'samsung' in title_lower:
                            brands.append('samsung')
                        elif 'xiaomi' in title_lower:
                            brands.append('xiaomi')


                    if any(word in title_lower for word in ['robot', 'supurge', 'vacuum', 'cleaner', 'dyson', 'irobot', 'roomba']):
                        categories.append('home_appliances')
                        keywords.extend(['robot', 'supurge', 'vacuum', 'cleaner', 'home'])
                        if 'dyson' in title_lower:
                            brands.append('dyson')


                    if any(word in title_lower for word in ['krema', 'kosmetik', 'kozmetik', 'cream', 'moisturizer', 'makyaj', 'parfum', 'şampuan']):
                        categories.append('cosmetics')
                        keywords.extend(['krema', 'cream', 'cosmetic', 'beauty', 'skincare'])


                    if any(word in title_lower for word in ['kilif', 'case', 'cover', 'kulaklik', 'headphone', 'earbuds']):
                        categories.append('accessories')
                        keywords.extend(['kilif', 'case', 'cover', 'accessory'])


                    if any(word in title_lower for word in ['tisort', 'gomlek', 'pantolon', 'ayakkabi', 'shirt', 'pants', 'shoes']):
                        categories.append('fashion')
                        keywords.extend(['fashion', 'clothing', 'wear'])


                    if any(word in title_lower for word in ['kulaklik', 'headphone', 'earbuds', 'mouse', 'keyboard', 'monitor']):
                        categories.append('electronics')
                        keywords.extend(['electronics', 'gadget', 'tech'])


            from collections import Counter
            category_counts = Counter(categories)
            brand_counts = Counter(brands)

            return {
                "has_subscriptions": True,
                "categories": category_counts.most_common(3),
                "brands": brand_counts.most_common(3),
                "keywords": list(set(keywords)),
                "total_subscriptions": len(subscriptions)
            }

    except Exception as e:
        logger.exception(f"Error analyzing user preferences for {user_id}: {e}")
        return {"categories": [], "brands": [], "has_subscriptions": False}

async def generate_recommendations(user_id: int, limit: int = 5) -> List[Dict[str, Any]]:
    """Generate personalized product recommendations"""
    try:
        import random
        preferences = analyze_user_preferences(user_id)

        if not preferences["has_subscriptions"]:
            return []

        recommendations = []
        available_products = get_available_products()


        user_brands = [brand.lower() for brand, _ in preferences["brands"]]

        for category, count in preferences["categories"]:
            category_products = [p for p in available_products if p["category"] == category]


            preferred_products = []
            other_products = []

            for product in category_products:
                product_brand = product.get("brand", "").lower()
                if product_brand in user_brands:
                    preferred_products.append(product)
                else:
                    other_products.append(product)


            selected_products = []
            preferred_count = min(len(preferred_products), max(1, int(limit * 0.7)))
            other_count = min(len(other_products), limit - preferred_count)

            if preferred_products:
                selected_products.extend(random.sample(preferred_products, min(preferred_count, len(preferred_products))))
            if other_products and len(selected_products) < limit:
                remaining_slots = limit - len(selected_products)
                selected_products.extend(random.sample(other_products, min(other_count, remaining_slots, len(other_products))))


            for product in selected_products:
                if len(recommendations) >= limit:
                    break

                reason = product.get("reason_template", "Рекомендуемый товар")
                if product.get("brand", "").lower() in user_brands:
                    reason = f"Вам нравится бренд {product['brand']}"
                elif category == "smartphones":
                    reason = "Популярный смартфон"
                elif category == "home_appliances":
                    reason = "Качественная бытовая техника"
                elif category == "cosmetics":
                    reason = "Популярное косметическое средство"
                elif category == "fashion":
                    reason = "Модная одежда"

                recommendations.append({
                    "title": product["title"],
                    "url": product["url"],
                    "price": product["price"],
                    "reason": reason
                })


        if not recommendations:
            general_products = [p for p in available_products if p.get("popular", False)]
            if general_products:
                selected = random.sample(general_products, min(limit, len(general_products)))
                for product in selected:
                    recommendations.append({
                        "title": product["title"],
                        "url": product["url"],
                        "price": product["price"],
                        "reason": "Популярный товар"
                    })


        random.shuffle(recommendations)

        return recommendations[:limit]

    except Exception as e:
        logger.exception(f"Error generating recommendations for {user_id}: {e}")
        return []

def get_available_products() -> List[Dict[str, Any]]:
    """Get list of available products for recommendations"""

    from database import get_recommended_products
    recommended_products = get_recommended_products()


    if recommended_products:
        return recommended_products


    return [

        {
            "title": "Samsung Galaxy S25 Ultra",
            "url": "https://www.trendyol.com/samsung/galaxy-s25-ultra-akilli-telefon-p-123456789",
            "price": "₺45,000",
            "category": "smartphones",
            "brand": "samsung",
            "reason_template": "Флагман Samsung"
        },
        {
            "title": "iPhone 16 Pro Max",
            "url": "https://www.trendyol.com/apple/iphone-16-pro-max-akilli-telefon-p-123456790",
            "price": "₺52,000",
            "category": "smartphones",
            "brand": "apple",
            "reason_template": "Новинка Apple"
        },
        {
            "title": "Xiaomi 14 Ultra",
            "url": "https://www.trendyol.com/xiaomi/xiaomi-14-ultra-akilli-telefon-p-123456791",
            "price": "₺35,000",
            "category": "smartphones",
            "brand": "xiaomi",
            "reason_template": "Отличное соотношение цена/качество"
        },
        {
            "title": "Huawei P60 Pro",
            "url": "https://www.trendyol.com/huawei/p60-pro-akilli-telefon-p-123456792",
            "price": "₺28,000",
            "category": "smartphones",
            "brand": "huawei",
            "reason_template": "Камера премиум-класса"
        },


        {
            "title": "Dyson V15 Detect",
            "url": "https://www.trendyol.com/dyson/v15-detect-robot-supurge-p-123456793",
            "price": "₺25,000",
            "category": "home_appliances",
            "brand": "dyson",
            "reason_template": "Премиум пылесос"
        },
        {
            "title": "iRobot Roomba j7",
            "url": "https://www.trendyol.com/irobot/roomba-j7-robot-supurge-p-123456794",
            "price": "₺22,000",
            "category": "home_appliances",
            "brand": "irobot",
            "reason_template": "Умный помощник по уборке"
        },
        {
            "title": "Narwal Freo X Ultra",
            "url": "https://www.trendyol.com/narwal/freo-x-ultra-robot-supurge-p-123456795",
            "price": "₺18,000",
            "category": "home_appliances",
            "brand": "narwal",
            "reason_template": "Компактный и мощный"
        },


        {
            "title": "La Mer Crème de la Mer",
            "url": "https://www.trendyol.com/la-mer/creme-de-la-mer-yuz-kremi-p-123456796",
            "price": "₺8,500",
            "category": "cosmetics",
            "brand": "la mer",
            "reason_template": "Люксовая косметика"
        },
        {
            "title": "The Ordinary Hyaluronic Acid",
            "url": "https://www.trendyol.com/the-ordinary/hyaluronic-acid-yuz-kremi-p-123456797",
            "price": "₺120",
            "category": "cosmetics",
            "brand": "the ordinary",
            "reason_template": "Доступная профессиональная косметика"
        },
        {
            "title": "CeraVe Moisturizing Cream",
            "url": "https://www.trendyol.com/cerave/moisturizing-cream-yuz-kremi-p-123456798",
            "price": "₺85",
            "category": "cosmetics",
            "brand": "cerave",
            "reason_template": "Для чувствительной кожи"
        },


        {
            "title": "Nike Air Max 270",
            "url": "https://www.trendyol.com/nike/air-max-270-erkek-spor-ayakkabi-p-123456799",
            "price": "₺2,850",
            "category": "fashion",
            "brand": "nike",
            "reason_template": "Популярные кроссовки"
        },
        {
            "title": "Adidas Ultraboost 22",
            "url": "https://www.trendyol.com/adidas/ultraboost-22-spor-ayakkabi-p-123456800",
            "price": "₺3,200",
            "category": "fashion",
            "brand": "adidas",
            "reason_template": "Комфорт и стиль"
        },


        {
            "title": "Sony WH-1000XM5",
            "url": "https://www.trendyol.com/sony/wh-1000xm5-kulaklik-p-123456801",
            "price": "₺8,500",
            "category": "electronics",
            "brand": "sony",
            "reason_template": "Шумоподавление премиум-класса"
        },
        {
            "title": "Logitech MX Master 3S",
            "url": "https://www.trendyol.com/logitech/mx-master-3s-mouse-p-123456802",
            "price": "₺1,850",
            "category": "electronics",
            "brand": "logitech",
            "reason_template": "Профессиональная мышь"
        }
    ]


@router.message(Command("alerts"))
async def cmd_alerts(message: types.Message):
    """Управление ценовыми алертами для всех подписок"""
    user_id = message.from_user.id
    add_user_if_not_exists(user_id)

    try:
        subs = get_user_subscriptions(user_id)
        if not subs:
            await message.answer(t(user_id, "no_subs"))
            return


        lines = [t(user_id, "alerts_header")]

        keyboard = []

        for index, sub in enumerate(subs, start=1):
            try:
                (sub_id, _, url, mode, last_price, product_title, product_image,
                 min_price, max_price, notify_percent, notify_interval, last_notify_time, price_alert, tags) = sub
            except ValueError:
                (sub_id, _, url, mode, last_price, product_title, product_image,
                 min_price, max_price, notify_percent, notify_interval, last_notify_time) = sub[:12]
                price_alert = None
                tags = None

            title = product_title if product_title else url[:40] + "..." if len(url) > 40 else url
            current_alert = f"{price_alert:.0f} TL" if price_alert else t(user_id, "alerts_not_set")

            lines.append(f"📦 <b>{title}</b>\n💰 {t(user_id, 'alerts_current')}: {current_alert}\n")


            keyboard.append([
                InlineKeyboardButton(
                    text=f"⚙️ {t(user_id, 'btn_edit')} № {index}",
                    callback_data=f"alert_edit:{sub_id}"
                )
            ])

        full_text = "\n".join(lines)

        if len(full_text) > 4000:
            await message.answer(t(user_id, "alerts_too_many"), parse_mode="HTML")
            return

        markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
        await message.answer(full_text, reply_markup=markup, parse_mode="HTML")

    except Exception as e:
        logger.exception("Error in cmd_alerts: %s", e)
        await message.answer(t(user_id, "error_generic"))

@router.message(Command("import"))
async def cmd_import(message: types.Message):
    """Импорт подписок из файла"""
    user_id = message.from_user.id
    add_user_if_not_exists(user_id)

    await message.answer(
        f"{t(user_id, 'import_help')}\n\n"
        f"📎 {t(user_id, 'import_instruction')}",
        parse_mode="HTML"
    )

async def cmd_compare_urls(message: types.Message):
    """Legacy helper: compare two direct URLs (router now lives in cmd_compare)."""
    user_id = message.from_user.id
    add_user_if_not_exists(user_id)

    args = message.text.split()
    if len(args) < 3:
        await message.answer(
            f"📊 <b>{t(user_id, 'cmd_compare_usage')}</b>\n\n"
            f"Пример:\n"
            f"<code>/compare https://trendyol.com/product1 https://trendyol.com/product2</code>",
            parse_mode="HTML"
        )
        return

    await _compare_products_by_urls(message, args[1], args[2])

@router.message(Command("recommend"))
async def cmd_recommend(message: types.Message):
    """Show personalized product recommendations"""
    user_id = message.from_user.id
    add_user_if_not_exists(user_id)

    status_message = await _send_progress_message(
        message,
        t(user_id, "recommend_loading"),
    )

    try:
        lang = get_user_language(user_id)
        custom_text = get_bot_text("recommend_text", lang)
        custom_text = custom_text.strip() if custom_text else None
        recommendations = await generate_recommendations(user_id, limit=5)

        if not recommendations:
            if custom_text:
                await _replace_progress_message(
                    status_message,
                    custom_text,
                    fallback_target=message,
                    parse_mode="HTML",
                )
            else:
                await _replace_progress_message(
                    status_message,
                    t(user_id, "recommend_no_data"),
                    fallback_target=message,
                )
            return

        response = f"{custom_text}\n\n" if custom_text else f"🎯 <b>{t(user_id, 'recommend_title')}</b>\n\n"

        keyboard = []

        for i, rec in enumerate(recommendations[:5], 1):
            response += f"{i}. <b>{rec['title']}</b>\n"
            response += f"💰 {rec['price']}\n"
            response += f"📝 {rec['reason']}\n\n"


            keyboard.append([
                InlineKeyboardButton(
                    text=f"🔍 {t(user_id, 'btn_view_product')} {i}",
                    url=rec['url']
                )
            ])

        if not custom_text:
            response += f"💡 {t(user_id, 'recommend_hint')}"

        markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
        await _replace_progress_message(
            status_message,
            response,
            fallback_target=message,
            reply_markup=markup,
            parse_mode="HTML",
        )

    except Exception as e:
        logger.exception("Error in cmd_recommend: %s", e)
        await _replace_progress_message(
            status_message,
            t(user_id, "error_generic"),
            fallback_target=message,
        )


async def cmd_health(message: types.Message):
    """Health check command"""
    user_id = message.from_user.id
    if not is_admin(user_id):
        await message.answer("❌ Доступ запрещен")
        return

    try:
        health_results = await perform_health_check()

        status_icon = "✅" if all(health_results.values()) else "⚠️"
        health_text = f"{status_icon} <b>HEALTH CHECK</b>\n\n"

        for check_name, result in health_results.items():
            icon = "✅" if result else "❌"
            health_text += f"{icon} {check_name}\n"


        health_text += f"\n⏰ Последняя проверка: {datetime.fromtimestamp(last_health_check).strftime('%H:%M:%S') if last_health_check else 'никогда'}"
        health_text += f"\n📊 Активных задач: {len(asyncio.all_tasks())}"

        await message.answer(health_text, parse_mode="HTML")

    except Exception as e:
        logger.exception("Error in health check: %s", e)
        await message.answer(f"❌ Ошибка проверки здоровья: {e}")

async def perform_health_check() -> dict:
    """Perform comprehensive health check"""
    global last_health_check
    results = {}

    try:

        import sqlite3
        conn = sqlite3.connect(DATABASE_PATH, timeout=5)
        conn.execute("SELECT 1")
        conn.close()
        results["База данных"] = True
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        results["База данных"] = False

    try:

        await _get_runtime_bot().get_me()
        results["Бот (Telegram API)"] = True
    except Exception as e:
        logger.error(f"Bot health check failed: {e}")
        results["Бот (Telegram API)"] = False

    try:

        if hasattr(scheduler, 'running') and scheduler.running:
            results["Планировщик задач"] = True
        else:
            results["Планировщик задач"] = False
    except Exception as e:
        logger.error(f"Scheduler health check failed: {e}")
        results["Планировщик задач"] = False

    try:

        from scraper import get_price_async

        test_result = await asyncio.wait_for(
            get_price_async("https://www.trendyol.com/cream-co/su-bazli-moisturizer-nemlendirici-aydinlatici-yuz-kremi-hyaluronik-asit-50-ml-tum-cilt-tipleri-p-318291787"),
            timeout=15
        )
        results["Парсер цен"] = test_result is not None
    except asyncio.TimeoutError:
        logger.warning("Scraper health check timed out")
        results["Парсер цен"] = False
    except Exception as e:
        logger.error(f"Scraper health check failed: {e}")
        results["Парсер цен"] = False


    last_health_check = int(time.time())

    return results


def _prune_decorated_legacy_handlers() -> None:
    """Drop decorator-registered legacy handlers replaced by handler classes."""
    legacy_message_callbacks = {

        "cmd_language_command",
        "cmd_lang_message",
        "cmd_help_button",

        "cmd_onboarding_try",
        "cmd_onboarding_skip",
        "cmd_onboarding_done",
    }

    before_msg = len(router.message.handlers)
    router.message.handlers[:] = [
        h for h in router.message.handlers
        if getattr(h.callback, "__name__", "") not in legacy_message_callbacks
    ]
    removed_msg = before_msg - len(router.message.handlers)

    if removed_msg:
        logger.info(
            "Pruned decorated legacy message handlers: message=%d",
            removed_msg,
        )


_handlers_registered = False


def register_application_handlers() -> None:
    """Register the single application handler stack."""
    global _handlers_registered
    if _handlers_registered:
        return

    logger.info("Using package handler architecture")
    try:
        _prune_decorated_legacy_handlers()
        from handlers import BasicHandler, SubscriptionHandler, AnalyticsHandler, CallbackHandler, AdminHandler
        basic_handler = BasicHandler()
        basic_handler.register(router)
        logger.info("Basic handlers registered")

        subscription_handler = SubscriptionHandler()
        subscription_handler.register(router)
        logger.info("Subscription handlers registered")

        analytics_handler = AnalyticsHandler()
        analytics_handler.register(router)
        logger.info("Analytics handlers registered")

        admin_handler = AdminHandler()
        admin_handler.register(router)
        logger.info("Admin handlers registered")

        callback_handler = CallbackHandler()
        callback_handler.register(router)
        logger.info("Callback handlers registered")
    except Exception as e:
        logger.critical("Failed to register application handlers: %s", e, exc_info=True)
        raise

    router.message.register(cmd_health, Command("health"))
    logger.info("Health command registered")
    _handlers_registered = True


register_application_handlers()


async def set_commands_menu():
    """Устанавливает меню команд для бота в Telegram"""
    from aiogram.types import BotCommand

    commands = [
        BotCommand(command="start", description="🚀 Start the bot"),
        BotCommand(command="help", description="❓ Help and commands"),
        BotCommand(command="mysubs", description="📦 My products"),
        BotCommand(command="compare", description="⚖️ Compare prices"),
        BotCommand(command="recommend", description="💡 Recommendations"),
        BotCommand(command="settings", description="⚙️ Bot settings"),
        BotCommand(command="language", description="🌐 Change language"),
        BotCommand(command="history", description="📈 Price history"),
        BotCommand(command="alerts", description="🔔 Manage alerts"),
        BotCommand(command="stats", description="📊 Statistics"),
        BotCommand(command="export", description="📤 Export data"),
        BotCommand(command="about", description="ℹ️ About the bot"),
        BotCommand(command="ping", description="🏓 Check bot response"),
        BotCommand(command="health", description="💚 Bot health status"),
    ]

    try:
        await _get_runtime_bot().set_my_commands(commands)
        logger.info("✅ Bot commands menu has been set successfully")
    except Exception as e:
        logger.warning("Failed to set bot commands menu: %s", e)
        action_event("WARN", "Telegram commands menu update failed", reason=short_value(e, 120))


async def shutdown_runtime() -> None:
    """Graceful runtime shutdown for polling mode."""
    try:
        if getattr(scheduler, "running", False):
            scheduler.shutdown(wait=False)
            logger.info("Scheduler shutdown completed")
    except Exception:
        logger.exception("Failed to shutdown scheduler cleanly")

    try:
        close_all_connections()
        logger.info("Database connection pool closed")
    except Exception:
        logger.exception("Failed to close database connections")

    try:
        if bot is not None:
            await bot.session.close()
            logger.info("Bot HTTP session closed")
    except Exception:
        logger.exception("Failed to close bot HTTP session")


async def main():
    runtime_bot, dispatcher = create_app()


    await set_commands_menu()


    try:
        await runtime_bot.delete_webhook(drop_pending_updates=True)
        logger.info("Webhook deleted / cleared (if existed)")
    except Exception as e:
        logger.warning("Failed to delete webhook (may be fine): %s", e)


    await start_scheduler_async(delay=0.0)

    logger.info("Bot polling started")
    action_event("START", "bot polling started")
    try:
        await dispatcher.start_polling(runtime_bot)
    finally:
        await shutdown_runtime()

if __name__ == "__main__":
    asyncio.run(main())
