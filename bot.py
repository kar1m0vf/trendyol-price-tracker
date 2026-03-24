import asyncio
import json
import logging
import sqlite3
import html
from typing import Optional, List, Tuple, Dict, Any
from datetime import datetime, timedelta
import io
import re
import os
import csv
import time
import aiohttp
from pathlib import Path
from urllib.parse import urlparse

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton, CallbackQuery
)

from config import BOT_TOKEN, _check_bot_token, USE_NEW_HANDLERS, ADMIN_IDS, DATABASE_PATH
from utils import get_next_notification_time
import aiogram
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
    set_bot_text,
    create_sqlite_backup,
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
from analytics import Analytics
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

                                                                               

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


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

                                                        
_check_bot_token()

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

                                                                            
notification_service = NotificationService(bot)

                                                                         
try:
    from config import DEFAULT_NOTIFY_MODE                            
except Exception:
    DEFAULT_NOTIFY_MODE = "hourly"                                                                  

                

                     
                                             
                        

                        
last_health_check = 0
health_check_interval = 60           

                              
alert_edit_state = {}                     
report_state = {}                          

                                
onboarding_state = {}                   

                                               
scheduler_lock = asyncio.Lock()
scheduler_start_lock = asyncio.Lock()
check_all_lock = asyncio.Lock()

init_db(run_maintenance=False)

             
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
        return await notification_service.send_notification_safe(
            user_id,
            text,
            image=image,
            timeout_seconds=timeout,
            parse_mode=parse_mode,
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
        return await notification_service.send_notification_safe(
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
        return await notification_service.send_history_plot(user_id, url, hist)
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
            InlineKeyboardButton(text=t(user_id, "btn_mode_hourly"), callback_data=f"mode:{sub_id}:hourly"),
            InlineKeyboardButton(text=t(user_id, "btn_mode_discount"), callback_data=f"mode:{sub_id}:discount")
        ]])
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=t(user_id, "btn_mode_hourly"), callback_data="mode:hourly"),
        InlineKeyboardButton(text=t(user_id, "btn_mode_discount"), callback_data="mode:discount")
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
            InlineKeyboardButton(text=mode_label_hourly, callback_data=f"mode:{sub_id}:hourly"),
            InlineKeyboardButton(text=mode_label_discount, callback_data=f"mode:{sub_id}:discount")
        ],
        [
            InlineKeyboardButton(text=t(user_id, "btn_history"), callback_data=f"history:{sub_id}"),
            InlineKeyboardButton(text=t(user_id, "btn_unsubscribe_inline"), callback_data=f"unsubscribe:{sub_id}")
        ],
        [
            InlineKeyboardButton(text=t(user_id, "btn_compare"), callback_data=f"compare:{sub_id}")
        ]
    ])

       
                                         
async def cmd_start_old(message: types.Message):
    user_id = _get_request_user_id(message)
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

@dp.message(_filter_language_button)
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

@dp.message(_filter_help_button)
async def cmd_help_button(message: types.Message):
    """Handle help button press"""
    await cmd_help_old(message)

@dp.message(_filter_onboarding_try)
async def cmd_onboarding_try(message: types.Message):
    """Handle onboarding try button"""
    user_id = message.from_user.id
    await send_onboarding_step(user_id, message)

@dp.message(_filter_onboarding_skip)
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

@dp.message(_filter_onboarding_done)
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

@dp.message(Command("language"))
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

@dp.message(Command("report"))
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

@dp.message(Command("history"))
async def cmd_history(message: types.Message):
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(t(message.from_user.id, "cmd_history_usage"))
        return
    arg = parts[1].strip()

                                  
    if arg.isdigit():
        sid = int(arg)
        sub = get_subscription(sid)
        if not sub or sub[1] != message.from_user.id:
            await message.answer(t(message.from_user.id, "no_subs"))
            return
                                                                                     
        if len(sub) >= 13:
            url = sub[2]
        elif len(sub) >= 12:
            url = sub[2]
        else:
            url = sub[2] if len(sub) > 2 else ""
        await message.answer(t(message.from_user.id, "history_fetching"))
                                    
        db_hist = get_price_history(sid, limit=1000)
        if db_hist and len(db_hist) >= 2:
                                                                                   
            hist = [(safe_ts_to_iso(r[0]), r[1]) for r in db_hist]
            await send_history_plot(message.from_user.id, url, hist)
            return

                                          
        hist = await get_price_history_from_akakce_async(url)
        if not hist:
            await message.answer(t(message.from_user.id, "history_not_found"))
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

        await send_history_plot(message.from_user.id, url, hist)
        return

                            
    url = normalize_url(arg)
    if "trendyol.com" not in url.lower():
        await message.answer(t(message.from_user.id, "not_trendyol"))
        return
    if not is_trendyol_product_url(url):
        await message.answer(t(message.from_user.id, "not_product_url"))
        return

    await message.answer(t(message.from_user.id, "history_fetching"))
    hist = await get_price_history_from_akakce_async(url)
    if not hist:
        await message.answer(t(message.from_user.id, "history_not_found"))
        return
    await send_history_plot(message.from_user.id, url, hist)

                                                        
async def cmd_unsubscribe_old(message: types.Message):
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer(t(message.from_user.id, "provide_subscription_id"))
        return
    sid = int(parts[1])
    sub = get_subscription(sid)
    if not sub or sub[1] != message.from_user.id:
        await message.answer(t(message.from_user.id, "no_subs"))
        return
    try:
        remove_subscription(sid)
        await message.answer(t(message.from_user.id, "sub_removed"))
    except Exception:
        await message.answer(t(message.from_user.id, "error_generic"))

                                                             
cmd_unsubscribe = cmd_unsubscribe_old

@dp.message(Command("setmode"))
async def cmd_setmode(message: types.Message):
    parts = (message.text or "").split()
    if len(parts) < 3 or not parts[1].isdigit():
        await message.answer(t(message.from_user.id, "cmd_setmode_usage"))
        return
    sid = int(parts[1])
    mode = parts[2].lower()
    if mode not in {"hourly", "discount"}:
        await message.answer(t(message.from_user.id, "provide_mode_options"))
        return
    sub = get_subscription(sid)
    if not sub:
        await message.answer(t(message.from_user.id, "no_subs_found_id"))
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

@dp.message(Command("price_alert"))
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
    
    sid = int(parts[1])
    
    try:
        target_price = float(parts[2])
    except ValueError:
        await message.answer(t(user_id, "price_alert_price_must_be_number"))
        return
    
    if target_price < 0:
        await message.answer(t(user_id, "price_alert_price_negative"))
        return
    
    sub = get_subscription(sid)
    if not sub:
        await message.answer(t(user_id, "price_alert_sub_not_found"))
        return
    
                                   
    if len(sub) >= 2 and sub[1] != user_id:
        await message.answer(t(user_id, "price_alert_not_your_sub"))
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

@dp.message(Command("about"))
async def cmd_about(message: types.Message):
    await message.answer(t(message.from_user.id, "about_text"))

@dp.message(Command("ping"))
async def cmd_ping(message: types.Message):
    await message.answer(t(message.from_user.id, "ping_pong"))

@dp.message(Command("settings"))
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
                sub_id = int(parts[2])
                sub = get_subscription(sub_id)
                if not sub or sub[1] != message.from_user.id:
                    await message.answer(t(message.from_user.id, "no_subs"))
                    return
                    
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
                sub_id = int(parts[2])
                minutes = int(parts[3])
                
                if minutes < 15:                                 
                    await message.answer(t(message.from_user.id, "interval_too_short"))
                    return
                    
                sub = get_subscription(sub_id)
                if not sub or sub[1] != message.from_user.id:
                    await message.answer(t(message.from_user.id, "no_subs"))
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

                                    
@dp.message(Command("runcheck"))
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
        
        sub_id = int(args[1])
        sub = get_subscription(sub_id)
        
        if not sub:
            await message.answer(t(message.from_user.id, "no_subs_found_id"))
            return
        
                             
        if sub[1] != message.from_user.id:
            await message.answer(t(message.from_user.id, "error_not_your_sub"))
            return
        
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

🏷️ ID: {sub_id}
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
        header += "`ID  | " + t(message.from_user.id, "mode") + "      | " + t(message.from_user.id, "price") + "    | " + t(message.from_user.id, "status") + "`\n"
        header += "`" + "—" * 38 + "`\n"
        
        rows = []
        for sub in subs:
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
            
            row = f"`{sub_id:3d} | {mode_short} {mode:8s} | {price_str:6s} | {alert_status}`"
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
            
            text += f"{i}. {icon} *{drop_pct:+.1f}%* | ID:{sub_id}\n"
            text += f"   {title_short}\n"
            text += f"   {t(message.from_user.id, 'current_price')}: {curr_str} TL | {t(message.from_user.id, 'min_price_label')}: {min_str} TL\n\n"
        
        await message.answer(text, parse_mode="Markdown")
        
    except Exception as e:
        logger.exception("Top drops command error: %s", e)
        await message.answer(t(message.from_user.id, "error_generic"))


                                                                                 
@dp.message(Command("export"))
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


                                                                   
@dp.message(Command("history_export"))
async def cmd_history_export(message: types.Message):
    try:
        parts = (message.text or "").split()
        if len(parts) < 2 or not parts[1].isdigit():
            await message.answer(t(message.from_user.id, "history_export_usage"))
            return

        sub_id = int(parts[1])
        fmt = "csv"
        days = None
                                                                   
        for p in parts[2:]:
            if p.lower() in {"csv", "json"}:
                fmt = p.lower()
            elif p.isdigit():
                days = int(p)

        sub = get_subscription(sub_id)
        if not sub:
            await message.answer(t(message.from_user.id, "no_subs"))
            return
        if len(sub) >= 2 and sub[1] != message.from_user.id:
            await message.answer(t(message.from_user.id, "error_not_your_sub"))
            return

                                                                                            
                                         
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


                                                                   
@dp.message(Command("history_plot"))
async def cmd_history_plot(message: types.Message):
    try:
        parts = (message.text or "").split()
        if len(parts) < 2 or not parts[1].isdigit():
            await message.answer(t(message.from_user.id, "history_plot_usage"))
            return

        sub_id = int(parts[1])
        days = None
        if len(parts) > 2 and parts[2].isdigit():
            days = int(parts[2])

        sub = get_subscription(sub_id)
        if not sub:
            await message.answer(t(message.from_user.id, "no_subs"))
            return
        if len(sub) >= 2 and sub[1] != message.from_user.id:
            await message.answer(t(message.from_user.id, "error_not_your_sub"))
            return

                                                     
        if days is not None:
            rows = get_local_price_history(sub_id, days=min(days, 180))                          
        else:
            rows = get_price_history(sub_id, limit=2000)                           

        if not rows:
            await message.answer(t(message.from_user.id, "history_plot_no_data"))
            return

                                                                 
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

    except Exception as e:
        logger.exception("history_plot error: %s", e)
        await message.answer(t(message.from_user.id, "error_generic"))


                                                 
@dp.message(Command("compare"))
async def cmd_compare(message: types.Message):
    """Unified compare command:
    - /compare <subscription_id>
    - /compare <url1> <url2>
    """
    user_id = message.from_user.id
    add_user_if_not_exists(user_id)
    args = (message.text or "").split()

    try:
                                                     
        if len(args) == 2 and args[1].isdigit():
            from scraper import get_similar_products_comparison

            sub_id = int(args[1])
            sub = get_subscription(sub_id)

            if not sub:
                await message.answer(t(user_id, "no_subs_found_id"))
                return

            if sub[1] != user_id:
                await message.answer(t(user_id, "error_not_your_sub"))
                return

            await message.answer(t(user_id, "compare_loading"))
            comparison = await get_similar_products_comparison(user_id, sub_id)
            if comparison:
                await message.answer(comparison, parse_mode="Markdown")
            else:
                await message.answer(t(user_id, "compare_no_similar"))
            return

                                                 
        if len(args) >= 3:
            await _compare_products_by_urls(message, args[1], args[2])
            return

        await message.answer(
            f"📊 <b>{t(user_id, 'cmd_compare_usage')}</b>\n\n"
            "Примеры:\n"
            "<code>/compare 123</code>\n"
            "<code>/compare https://trendyol.com/product1 https://trendyol.com/product2</code>",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.exception("compare command error: %s", e)
        await message.answer(t(user_id, "error_generic"))


async def _compare_products_by_urls(message: types.Message, url1: str, url2: str) -> None:
    """Compare prices for two direct product URLs."""
    user_id = message.from_user.id

    if not (is_trendyol_product_url(url1) and is_trendyol_product_url(url2)):
        await message.answer(t(user_id, "not_product_url"))
        return

    await message.answer(t(user_id, "compare_loading"))

    try:
                                                           
        (price1, title1, _), (price2, title2, _) = await asyncio.gather(
            get_product_info_async(url1),
            get_product_info_async(url2),
        )

        if price1 is None or price2 is None:
            await message.answer(t(user_id, "compare_error_no_price"))
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
        await message.answer(comparison_text, parse_mode="HTML")
    except Exception as e:
        logger.exception("Error in URL compare command: %s", e)
        await message.answer(t(user_id, "error_generic"))


                                                               
                                                    
async def callback_handler_old(cq: CallbackQuery):
    data = cq.data or ""
    user_id = cq.from_user.id
    logger.info(f"Legacy callback received: data='{data}', user={user_id}")

    try:
                                   
        if data == "help:full":
            await cq.answer()
            await cq.message.edit_text(t(user_id, "help_full"))
            return

                             
        if data.startswith("lang:"):
            await cq.answer()
            lang = data.split(":", 1)[1]
            set_user_language(user_id, lang)
                                                    
            from localization import update_language_cache
            update_language_cache(user_id, lang)
            try:
                await bot.send_message(
                    user_id,
                    t(user_id, "start_text"),
                    reply_markup=get_main_kb(user_id),
                    parse_mode="Markdown",
                )
                await cq.message.edit_text(t(user_id, "lang_changed"))
            except aiogram.exceptions.TelegramBadRequest as e:
                logger.warning("Bad request updating language for %s: %s", user_id, e)
            except Exception as e:
                logger.exception("Failed to send updated main kb or edit msg for %s: %s", user_id, e)
            return

                                          
        if data.startswith("unsubscribe:"):
            try:
                sub_id = int(data.split(":", 1)[1])
                sub = get_subscription(sub_id)
                if sub and sub[1] == user_id:
                    remove_subscription(sub_id)
                    await cq.message.edit_text(t(user_id, "sub_removed"))
                else:
                    await cq.answer(t(user_id, "error_not_your_sub"), show_alert=True)
            except ValueError as e:
                logger.warning("Invalid subscription ID in unsubscribe callback: %s", data)
                await cq.answer(t(user_id, "error_invalid_id"), show_alert=True)
            except sqlite3.DatabaseError as e:
                logger.error("Database error in unsubscribe callback: %s", e)
                await cq.answer(t(user_id, "error_database"), show_alert=True)
            except Exception as e:
                logger.exception("Unexpected unsubscribe callback error: %s", e)
                await cq.answer(t(user_id, "error_generic"), show_alert=True)
            return

                                                
        if data.startswith("confirm_unsub_all:"):
            await cq.answer()
            try:
                ans = data.split(":", 1)[1]
                if ans == "yes":
                    remove_subscriptions_by_user(user_id)
                    await cq.message.edit_text(t(user_id, "unsubscribed_all"))
                else:
                    await cq.message.edit_text(t(user_id, "action_cancelled"))
            except Exception as e:
                logger.exception("confirm_unsub_all error: %s", e)
                await cq.message.edit_text(t(user_id, "error_generic"))
            return

                                          
        if data.startswith("mode:"):
            parts = data.split(":")
            if len(parts) == 3:
                _, sub_id_str, mode = parts
                try:
                    sub_id = int(sub_id_str)
                    sub = get_subscription(sub_id)
                    logger.debug("mode callback: sub=%r user=%s", sub, user_id)
                                                             
                    if not sub:
                        await cq.answer(t(user_id, "no_subs"), show_alert=True)
                        return
                    owner_ok = False
                    try:
                        owner_ok = (len(sub) >= 2 and sub[1] == user_id)
                    except Exception:
                        owner_ok = False
                    if not owner_ok:
                        await cq.answer(t(user_id, "error_not_your_sub"), show_alert=True)
                        return

                    try:
                        update_mode(sub_id, mode)
                    except Exception as e:
                        logger.exception("update_mode error for sub %s: %s", sub_id, e)
                        await cq.answer(t(user_id, "error_generic"), show_alert=True)
                        return

                                                                     
                    try:
                        await cq.message.edit_reply_markup(reply_markup=subscription_controls_kb_for_user(user_id, sub_id))
                        await cq.answer(t(user_id, "mode_changed_short").format(mode=mode))
                    except Exception as e:
                        logger.exception("mode callback UI update failed for sub %s: %s", sub_id, e)
                                                                                      
                        try:
                            await cq.answer(t(user_id, "mode_changed_short").format(mode=mode))
                        except:
                            pass
                except ValueError:
                    await cq.answer(t(user_id, "error_generic"), show_alert=True)
                except Exception as e:
                    logger.exception("mode callback unexpected error: %s", e)
                    await cq.answer(t(user_id, "error_generic"), show_alert=True)
            return

                                         
        if data.startswith("edit_sub:"):
            await cq.answer()
            try:
                sub_id = int(data.split(":", 1)[1])
                sub = get_subscription(sub_id)
                if not sub or sub[1] != user_id:
                    await cq.answer(t(user_id, "error_not_your_sub"), show_alert=True)
                    return
                
                                                           
                try:
                    (_, _, url, mode, last_price, product_title, product_image,
                     min_price, max_price, notify_percent, notify_interval, last_notify_time, price_alert) = sub
                except ValueError:
                    (_, _, url, mode, last_price, product_title, product_image,
                     min_price, max_price, notify_percent, notify_interval, last_notify_time) = sub[:12]
                    price_alert = None
                
                                                          
                title = product_title if product_title else url[:60] + "..." if len(url) > 60 else url
                price_text = f"{last_price:.0f} TL" if last_price is not None else t(user_id, "unknown_price")
                mode_text = t(user_id, "mode_hourly") if mode == "hourly" else t(user_id, "mode_discount")
                
                edit_text = f"⚙️ *{t(user_id, 'edit_subscription')}*\n\n"
                edit_text += f"📦 {title}\n"
                edit_text += f"🔗 {url[:50]}...\n\n"
                edit_text += f"💰 {t(user_id, 'current_price')}: {price_text}\n"
                edit_text += f"🔔 {t(user_id, 'mode')}: {mode_text}\n"
                
                if price_alert is not None:
                    edit_text += f"🎯 {t(user_id, 'price_alert_label')}: {price_alert:.0f} TL\n"
                if min_price is not None:
                    edit_text += f"📉 {t(user_id, 'min_price_label')}: {min_price:.0f} TL\n"
                if max_price is not None:
                    edit_text += f"📈 {t(user_id, 'max_price_label')}: {max_price:.0f} TL\n"
                if notify_percent is not None:
                    edit_text += f"📊 {t(user_id, 'notify_percent')}: {notify_percent:.1f}%\n"
                if notify_interval is not None and notify_interval != 60:
                    edit_text += f"⏰ {t(user_id, 'interval')}: {notify_interval} {t(user_id, 'minutes')}\n"
                
                                                            
                await bot.send_message(
                    user_id,
                    edit_text,
                    reply_markup=subscription_controls_kb_for_user(user_id, sub_id),
                    parse_mode="Markdown"
                )
                await cq.answer()
            except Exception as e:
                logger.exception("edit_sub callback error: %s", e)
                await cq.answer(t(user_id, "error_generic"), show_alert=True)
            return

                                                
        if data.startswith("alert_edit:"):
            await cq.answer()
            try:
                sub_id = int(data.split(":", 1)[1])
                sub = get_subscription(sub_id)
                if not sub or sub[1] != user_id:
                    await cq.answer(t(user_id, "error_not_your_sub"), show_alert=True)
                    return

                try:
                    (_, _, url, mode, last_price, product_title, product_image,
                     min_price, max_price, notify_percent, notify_interval, last_notify_time, price_alert) = sub
                except ValueError:
                    (_, _, url, mode, last_price, product_title, product_image,
                     min_price, max_price, notify_percent, notify_interval, last_notify_time) = sub[:12]
                    price_alert = None

                title = product_title if product_title else url[:50] + "..." if len(url) > 50 else url
                current_alert = f"{price_alert:.0f} TL" if price_alert else t(user_id, "alerts_not_set")

                alert_text = f"""
⚙️ <b>{t(user_id, 'alerts_edit_title')}</b>

📦 {title}
💰 {t(user_id, 'current_price')}: {last_price:.0f} TL
🎯 {t(user_id, 'alerts_current')}: {current_alert}

{t(user_id, 'alerts_edit_help')}
"""

                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text=f"❌ {t(user_id, 'alerts_remove')}",
                        callback_data=f"alert_remove:{sub_id}"
                    )],
                    [InlineKeyboardButton(
                        text=f"🔙 {t(user_id, 'btn_back')}",
                        callback_data="alerts_back"
                    )]
                ])

                await bot.send_message(user_id, alert_text, reply_markup=keyboard, parse_mode="HTML")
                alert_edit_state[user_id] = sub_id                                          
                await cq.answer()

            except ValueError:
                await cq.answer(t(user_id, "error_invalid_id"), show_alert=True)
            except Exception as e:
                logger.exception("alert_edit callback error: %s", e)
                await cq.answer(t(user_id, "error_generic"), show_alert=True)
            return

                                 
        if data.startswith("alert_remove:"):
            try:
                sub_id = int(data.split(":", 1)[1])
                sub = get_subscription(sub_id)
                if not sub or sub[1] != user_id:
                    await cq.answer(t(user_id, "error_not_your_sub"), show_alert=True)
                    return

                update_subscription_settings(sub_id, price_alert=None)
                await cq.message.edit_text(
                    f"✅ {t(user_id, 'alerts_removed_success')}",
                    reply_markup=None
                )
                await cq.answer()

            except Exception as e:
                logger.exception("alert_remove callback error: %s", e)
                await cq.answer(t(user_id, "error_generic"), show_alert=True)
            return

                                          
        if data == "alerts_back":
            await cq.answer()
                                              
            await cmd_alerts(cq.message)
            return

                                    
        if data.startswith("history:"):
            await cq.answer(t(user_id, "history_fetching_short"))
            try:
                sid = int(data.split(":", 1)[1])
                sub = get_subscription(sid)
                if not sub or sub[1] != user_id:
                    await bot.send_message(user_id, t(user_id, "error_not_your_sub"))
                    return
                url = sub[2]
                                   
                db_hist = get_price_history(sid, limit=1000)
                if db_hist and len(db_hist) >= 2:
                    hist = [(safe_ts_to_iso(r[0]), r[1]) for r in db_hist]
                    await send_history_plot(user_id, url, hist)
                    return

                hist = await get_price_history_from_akakce_async(url)
                if not hist:
                    await bot.send_message(user_id, t(user_id, "history_not_found"))
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
                await send_history_plot(user_id, url, hist)
            except Exception as e:
                logger.exception("history callback error: %s", e)
                await bot.send_message(user_id, t(user_id, "error_generic"))
            return

                               
        if data.startswith("compare:"):
            await cq.answer(t(user_id, "compare_loading"))
            try:
                from scraper import get_comparison_report

                sid = int(data.split(":", 1)[1])
                sub = get_subscription(sid)
                if not sub or sub[1] != user_id:
                    await bot.send_message(user_id, t(user_id, "error_not_your_sub"))
                    return

                comparison = await get_comparison_report(user_id, sid)
                if comparison:
                    await bot.send_message(user_id, comparison, parse_mode="Markdown")
                else:
                    await bot.send_message(user_id, t(user_id, "compare_no_similar"))

            except Exception as e:
                logger.exception("compare callback error: %s", e)
                await bot.send_message(user_id, t(user_id, "error_generic"))
            return

                              
        if data == "trend:all":
            await cq.answer()
            await bot.send_message(user_id, t(user_id, "please_wait"))
            try:
                items = await get_trending_all_top3_async()
                await send_trending_list(user_id, items)
                await cq.message.delete()                        
            except Exception as e:
                logger.exception("trending all error: %s", e)
                await bot.send_message(user_id, t(user_id, "trending_no_results"))
            return

        if data == "trend:catmenu":
            await cq.answer()
            await cq.message.edit_text(t(user_id, "trending_choose_category"), reply_markup=trending_categories_kb(user_id))
            return

        if data.startswith("trend:cat:"):
            await cq.answer()
            cat = data.split(":", 2)[-1]
            await bot.send_message(user_id, t(user_id, "please_wait"))
            try:
                items = await get_trending_by_category_top3_async(cat)
                await send_trending_list(user_id, items)
                await cq.message.delete()
            except Exception as e:
                logger.exception("trending cat error: %s", e)
                await bot.send_message(user_id, t(user_id, "trending_no_results"))
            return

        if data == "trend:search":
            await cq.answer()
            TREND_SEARCH_AWAIT.add(user_id)
            await cq.message.edit_text(t(user_id, "trending_enter_query"))
            return

                                    
        if data.startswith("user_details:"):
            if not is_admin(user_id):
                await cq.answer(t(user_id, "admin_only"), show_alert=True)
                return

            try:
                target_user_id = int(data.split(":", 1)[1])
                await cq.answer(t(user_id, "loading"))

                                        
                await admin_user_details_callback(cq.message, target_user_id, user_id)
            except ValueError:
                await cq.answer(t(user_id, "error_invalid_id"), show_alert=True)
            except Exception as e:
                logger.exception("user_details callback error: %s", e)
                await cq.answer(t(user_id, "error_generic"), show_alert=True)
            return

                                     
        if data == "admin_users_refresh":
            if not is_admin(user_id):
                await cq.answer(t(user_id, "admin_only"), show_alert=True)
                return

            await cq.answer(t(user_id, "loading"))
            try:
                                         
                await admin_users_list_interactive(cq.message)
            except Exception as e:
                logger.exception("admin_users_refresh callback error: %s", e)
                await cq.answer(t(user_id, "error_generic"), show_alert=True)
            return

                                 
        if data == "admin_main_menu":
            if not is_admin(user_id):
                await cq.answer(t(user_id, "admin_only"), show_alert=True)
                return

            await cq.answer()
            try:
                await admin_main_menu(cq.message)
            except Exception as e:
                logger.exception("admin_main_menu callback error: %s", e)
                await cq.answer(t(user_id, "error_generic"), show_alert=True)
            return

                             
        if data == "admin_stats" or data == "admin_stats_refresh":
            if not is_admin(user_id):
                await cq.answer(t(user_id, "admin_only"), show_alert=True)
                return

            await cq.answer(t(user_id, "loading"))
            try:
                await admin_stats(cq.message)
            except Exception as e:
                logger.exception("admin_stats callback error: %s", e)
                await cq.answer(t(user_id, "error_generic"), show_alert=True)
            return

                             
        if data == "admin_users":
            if not is_admin(user_id):
                await cq.answer(t(user_id, "admin_only"), show_alert=True)
                return

            await cq.answer(t(user_id, "loading"))
            try:
                await admin_users_list_interactive(cq.message)
            except Exception as e:
                logger.exception("admin_users callback error: %s", e)
                await cq.answer(t(user_id, "error_generic"), show_alert=True)
            return

                                     
        if data == "admin_check_blocked":
            if not is_admin(user_id):
                await cq.answer(t(user_id, "admin_only"), show_alert=True)
                return

            await cq.answer(t(user_id, "loading"))
            try:
                await admin_check_blocked(cq.message)
            except Exception as e:
                logger.exception("admin_check_blocked callback error: %s", e)
                await cq.answer(t(user_id, "error_generic"), show_alert=True)
            return

                                 
        if data == "admin_recommend":
            if not is_admin(user_id):
                await cq.answer(t(user_id, "admin_only"), show_alert=True)
                return

            await cq.answer()
            try:
                await admin_recommend(cq.message, [])
            except Exception as e:
                logger.exception("admin_recommend callback error: %s", e)
                await cq.answer(t(user_id, "error_generic"), show_alert=True)
            return

                                         
        if data.startswith("admin_recommend_"):
            if not is_admin(user_id):
                await cq.answer(t(user_id, "admin_only"), show_alert=True)
                return

            await cq.answer()
            try:
                action = data.replace("admin_recommend_", "")
                if action == "list":
                    await _admin_recommend_list(cq.message)
                elif action == "add":
                                                 
                    keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="📚 Справка по формату", callback_data="admin_recommend_help")]
                    ])
                    await cq.message.edit_text(
                        "➕ <b>Добавление товара</b>\n\n"
                        "Используйте команду:\n"
                        "<code>/admin recommend add \"Название\" \"https://ссылка\"</code>\n\n"
                        "Пример:\n"
                        "<code>/admin recommend add \"iPhone 15 Pro\" \"https://trendyol.com/iphone-p-123\"</code>",
                        reply_markup=keyboard,
                        parse_mode="HTML"
                    )
                elif action == "remove":
                                                    
                    await cq.message.edit_text(
                        "🗑️ <b>Удаление товара</b>\n\n"
                        "Используйте команду:\n"
                        "<code>/admin recommend remove ID</code>\n\n"
                        "Сначала посмотрите список товаров:",
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="📋 Посмотреть список", callback_data="admin_recommend_list")]
                        ]),
                        parse_mode="HTML"
                    )
                elif action == "priority":
                    await cq.message.edit_text(
                        "⭐ <b>Изменение приоритета</b>\n\n"
                        "Используйте команду:\n"
                        "<code>/admin recommend priority ID приоритет</code>\n\n"
                        "Пример: <code>/admin recommend priority 5 10</code>",
                        parse_mode="HTML"
                    )
                elif action == "text":
                    lang = get_user_language(user_id)
                    current = get_bot_text("recommend_text", lang) or ""
                    preview = html.escape(current) if current else "—"
                    await cq.message.edit_text(
                        "✏️ <b>Текст рекомендаций</b>\n\n"
                        "Текущий текст:\n"
                        f"<code>{preview}</code>\n\n"
                        "Установить:\n"
                        "<code>/admin recommend text Ваш текст</code>\n\n"
                        "Очистить:\n"
                        "<code>/admin recommend text clear</code>\n\n"
                        "Поддерживается HTML: <b>, <i>, <code>, <a href=\"...\">...</a>",
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_recommend")]
                        ]),
                        parse_mode="HTML",
                        disable_web_page_preview=True,
                    )
                elif action == "help":
                    await cq.message.edit_text(
                        "📚 <b>Справка по управлению товарами</b>\n\n"
                        "<b>Добавление:</b>\n"
                        "<code>/admin recommend add \"Название\" \"URL\" [цена] [категория] [бренд]</code>\n\n"
                        "<b>Удаление:</b>\n"
                        "<code>/admin recommend remove ID</code>\n\n"
                        "<b>Приоритет:</b>\n"
                        "<code>/admin recommend priority ID число</code>\n\n"
                        "<b>Текст:</b>\n"
                        "<code>/admin recommend text ...</code>\n\n"
                        "<b>Список:</b>\n"
                        "<code>/admin recommend list</code>",
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_recommend")]
                        ]),
                        parse_mode="HTML"
                    )
            except Exception as e:
                logger.exception(f"admin_recommend_{action} callback error: %s", e)
                await cq.answer(t(user_id, "error_generic"), show_alert=True)
            return

                                                     
        if data.startswith("admin_product_delete_"):
            if not is_admin(user_id):
                await cq.answer(t(user_id, "admin_only"), show_alert=True)
                return

            await cq.answer()
            try:
                product_id = int(data.replace("admin_product_delete_", ""))
                from database import remove_recommended_product

                if remove_recommended_product(product_id):
                    keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="📋 Список товаров", callback_data="admin_recommend_list")],
                        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_recommend")]
                    ])
                    await cq.message.edit_text(
                        f"🗑️ <b>Товар #{product_id} удалён</b>",
                        reply_markup=keyboard,
                        parse_mode="HTML"
                    )
                else:
                    await cq.answer("Товар не найден", show_alert=True)
            except Exception as e:
                logger.exception("admin_product_delete callback error: %s", e)
                await cq.answer(t(user_id, "error_generic"), show_alert=True)
            return

                                                       
        if data.startswith("admin_product_priority_"):
            if not is_admin(user_id):
                await cq.answer(t(user_id, "admin_only"), show_alert=True)
                return

            await cq.answer()
            try:
                product_id = int(data.replace("admin_product_priority_", ""))
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="📋 Список товаров", callback_data="admin_recommend_list")],
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_recommend")]
                ])
                await cq.message.edit_text(
                    "⭐ <b>Изменение приоритета</b>\n\n"
                    "Используйте команду:\n"
                    f"<code>/admin recommend priority {product_id} ПРИОРИТЕТ</code>\n\n"
                    "Пример:\n"
                    f"<code>/admin recommend priority {product_id} 10</code>",
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.exception("admin_product_priority callback error: %s", e)
                await cq.answer(t(user_id, "error_generic"), show_alert=True)
            return

                                       
        if data.startswith("admin_product_"):
            if not is_admin(user_id):
                await cq.answer(t(user_id, "admin_only"), show_alert=True)
                return

            await cq.answer()
            try:
                product_id = int(data.replace("admin_product_", ""))
                from database import get_recommended_products

                products = get_recommended_products()
                product = next((p for p in products if p['id'] == product_id), None)

                if not product:
                    await cq.answer("Товар не найден", show_alert=True)
                    return

                                                          
                text = f"📦 <b>{product['title']}</b>\n\n"
                text += f"🆔 ID: <code>{product['id']}</code>\n"
                text += f"💰 Цена: {product['price'] or 'Не указана'}\n"
                text += f"🎯 Категория: {product['category'] or 'Не указана'}\n"
                text += f"🏷️ Бренд: {product['brand'] or 'Не указан'}\n"
                text += f"⭐ Приоритет: {product.get('priority', 0)}\n"
                text += f"🔗 Ссылка: {product['url'][:50]}...\n\n"
                text += f"📝 {product.get('reason', 'Рекомендуемый товар')}"

                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [
                        InlineKeyboardButton(text="🗑️ Удалить", callback_data=f"admin_product_delete_{product_id}"),
                        InlineKeyboardButton(text="⭐ Изменить приоритет", callback_data=f"admin_product_priority_{product_id}")
                    ],
                    [
                        InlineKeyboardButton(text="📋 К списку", callback_data="admin_recommend_list"),
                        InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_recommend")
                    ]
                ])

                await cq.message.edit_text(
                    text,
                    reply_markup=keyboard,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )

            except Exception as e:
                logger.exception(f"admin_product_{product_id} callback error: %s", e)
                await cq.answer(t(user_id, "error_generic"), show_alert=True)
            return

                                      
        if data == "admin_broadcast_menu":
            if not is_admin(user_id):
                await cq.answer(t(user_id, "admin_only"), show_alert=True)
                return

            await cq.answer()
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📢 Начать рассылку", callback_data="admin_broadcast_start")],
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_main_menu")]
            ])

            await cq.message.edit_text(
                "📢 <b>Рассылка сообщений</b>\n\n"
                "Используйте команду:\n"
                "<code>/admin broadcast &lt;сообщение&gt;</code>\n\n"
                "Пример:\n"
                "<code>/admin broadcast Привет! У нас новинка в разделе рекомендаций!</code>\n\n"
                "<b>⚠️ Внимание:</b> Сообщение будет отправлено всем пользователям бота.",
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            return

                                                
        if data == "admin_broadcast_start":
            if not is_admin(user_id):
                await cq.answer(t(user_id, "admin_only"), show_alert=True)
                return

            await cq.answer()
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_main_menu")]
            ])
            await cq.message.edit_text(
                "📢 <b>Рассылка сообщений</b>\n\n"
                "Отправьте команду:\n"
                "<code>/admin broadcast &lt;сообщение&gt;</code>\n\n"
                "Пример:\n"
                "<code>/admin broadcast Привет! У нас новинка в разделе рекомендаций!</code>\n\n"
                "<b>⚠️ Внимание:</b> сообщение получат все пользователи бота.",
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            return

                               
        if data == "admin_cleanup":
            if not is_admin(user_id):
                await cq.answer(t(user_id, "admin_only"), show_alert=True)
                return

            await cq.answer()
            try:
                await admin_cleanup(cq.message)
            except Exception as e:
                logger.exception("admin_cleanup callback error: %s", e)
                await cq.answer(t(user_id, "error_generic"), show_alert=True)
            return

                              
        if data == "admin_backup":
            if not is_admin(user_id):
                await cq.answer(t(user_id, "admin_only"), show_alert=True)
                return

            await cq.answer()
            try:
                await admin_backup(cq.message)
            except Exception as e:
                logger.exception("admin_backup callback error: %s", e)
                await cq.answer(t(user_id, "error_generic"), show_alert=True)
            return

                            
        if data == "admin_help":
            if not is_admin(user_id):
                await cq.answer(t(user_id, "admin_only"), show_alert=True)
                return

            await cq.answer()
            help_text = "📚 <b>Справка по админ функциям</b>\n\n"
            help_text += "🎯 <b>Рекомендации:</b>\n"
            help_text += "• Добавляйте товары для рекламы\n"
            help_text += "• Управляйте приоритетами показа\n"
            help_text += "• Отслеживайте эффективность\n\n"
            help_text += "👥 <b>Пользователи:</b>\n"
            help_text += "• Просматривайте активность\n"
            help_text += "• Проверяйте блокировки\n"
            help_text += "• Управляйте доступом\n\n"
            help_text += "📊 <b>Статистика:</b>\n"
            help_text += "• Мониторьте использование\n"
            help_text += "• Отслеживайте рост\n"
            help_text += "• Анализируйте тренды"

            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_main_menu")]
            ])

            await cq.message.edit_text(help_text, reply_markup=keyboard, parse_mode="HTML")
            return

        await cq.answer()

    except Exception as e:
        logger.exception("callback_handler error: %s", e)
        try:
            await cq.answer(t(user_id, "error_generic"), show_alert=True)
        except aiogram.exceptions.TelegramAPIError:
            logger.warning("Could not send error alert to user %s", user_id)
        except Exception as inner_e:
            logger.error("Failed to send error alert: %s", inner_e)

                                     
                                                    
async def admin_user_details_callback_old(cq: CallbackQuery):
    """Handle user details button clicks in admin panel"""
    try:
                                 
        if cq.from_user.id not in ADMIN_IDS:
            await cq.answer(t(cq.from_user.id, "admin_only"), show_alert=True)
            return

                                            
        target_user_id = int(cq.data.split(":", 1)[1])

        await cq.answer(t(cq.from_user.id, "loading_user_details"))

                                       
        await admin_user_details_callback(cq.message, target_user_id, cq.from_user.id)

    except ValueError:
        await cq.answer(t(cq.from_user.id, "invalid_user_id"), show_alert=True)
    except Exception as e:
        logger.exception("Error in admin_user_details_callback: %s", e)
        await cq.answer(t(cq.from_user.id, "error_generic"), show_alert=True)

                    
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

@dp.message(_filter_subscribe_button)
async def cmd_subscribe_ui(message: types.Message):
    await message.answer(t(message.from_user.id, "send_link_prompt"))

                                                        
async def handle_url_old(message: types.Message):
    try:
        raw = (message.text or "").strip()
        
                                        
        if not raw or len(raw) < 10:
            await message.answer(t(message.from_user.id, "invalid_url"))
            return
        
        url = await resolve_short_url(raw)
        url = normalize_url(url)
        url_lower = url.lower()

        if "trendyol.com" not in url_lower and "ty.gl/" not in url_lower:
            await message.answer(t(message.from_user.id, "not_trendyol"))
            return

        if not is_trendyol_product_url(url):
            await message.answer(t(message.from_user.id, "not_product_url"))
            return

        add_user_if_not_exists(message.from_user.id)

                                           
        subs = get_user_subscriptions(message.from_user.id)
        for sub in subs:
            try:
                (sid, user_id, u, mode, last_price, product_title, product_image,
                 min_price, max_price, notify_percent, notify_interval, last_notify_time, price_alert) = sub
            except ValueError:
                                              
                (sid, user_id, u, mode, last_price, product_title, product_image,
                 min_price, max_price, notify_percent, notify_interval, last_notify_time) = sub[:12]
            if normalize_url(u).lower() == url_lower:
                await message.answer(t(message.from_user.id, "already_subscribed"))
                return

                                                                          
        sub_id = add_subscription(message.from_user.id, url, DEFAULT_NOTIFY_MODE)
                                                           
        try:
            price, title, image = await get_product_info_async(url)
        except asyncio.TimeoutError:
            logger.warning("Timeout fetching product info for subscription: %s", url)
            await message.answer(t(message.from_user.id, "error_timeout"))
            price, title, image = None, None, None
        except aiohttp.ClientError as e:
            logger.warning("Network error fetching product info for subscription %s: %s", url, e)
            await message.answer(t(message.from_user.id, "error_network"))
            price, title, image = None, None, None
        except Exception as e:
            logger.exception("Unexpected error fetching product info for subscription: %s", e)
            await message.answer(t(message.from_user.id, "error_generic"))
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
                                                            
                text = t(message.from_user.id, "subscribed_now").format(price=price)
                if title:
                    text = f"{title}\n\n" + text
                if image:
                    try:
                        await bot.send_photo(message.from_user.id, photo=image, caption=text,
                                             reply_markup=subscription_controls_kb_for_user(message.from_user.id, sub_id))
                    except Exception:
                        await message.answer(text, reply_markup=subscription_controls_kb_for_user(message.from_user.id, sub_id))
                else:
                    await message.answer(text, reply_markup=subscription_controls_kb_for_user(message.from_user.id, sub_id))
            except Exception:
                await message.answer(
                    t(message.from_user.id, "subscribed"),
                    reply_markup=subscription_controls_kb_for_user(message.from_user.id, sub_id)
                )
        else:
            text = t(message.from_user.id, "subscribed_no_price")
            if title:
                text = f"{title}\n\n" + text
            await message.answer(text, reply_markup=subscription_controls_kb_for_user(message.from_user.id, sub_id))

    except Exception as e:
        logger.exception("Error in handle_url for user %s: %s", message.from_user.id, e)
        await message.answer(t(message.from_user.id, "error_generic"))

                                                                                    
handle_url = handle_url_old

                              
def _filter_alert_price(message: types.Message) -> bool:
    """Filter for alert price input"""
    if not message.from_user or not message.text:
        return False
    return message.from_user.id in alert_edit_state and not message.text.startswith("/")

@dp.message(_filter_alert_price)
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

@dp.message(_filter_report_text)
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

@dp.message(_filter_mysubs)
async def cmd_mysubs(message: types.Message):
    user_id = message.from_user.id
    subs = get_user_subscriptions(user_id)
    if not subs:
        await message.answer(t(user_id, "no_subs"))
        return
    
                                                       
    lines = [t(user_id, "mysubs_header")]
    inline_buttons = []
    
    for sub in subs:
        try:
            (sub_id, _, url, mode, last_price, product_title, product_image,
             min_price, max_price, notify_percent, notify_interval, last_notify_time, price_alert) = sub
        except ValueError:
                                          
            (sub_id, _, url, mode, last_price, product_title, product_image,
             min_price, max_price, notify_percent, notify_interval, last_notify_time) = sub[:12]
            price_alert = None
        
                                    
        status_icon = "✅" if last_price is not None else "⚠️"
        status_text = t(user_id, "status_active") if last_price is not None else t(user_id, "status_inactive")
        
                          
        price_text = f"{last_price:.0f} TL" if last_price is not None else t(user_id, "unknown_price")
        
                                                          
        mode_text = t(user_id, "mode_hourly") if mode == "hourly" else t(user_id, "mode_discount")
        next_notify = get_next_notification_time(mode, last_notify_time, notify_interval, user_id)

                                            
        title = product_title if product_title else url[:50] + "..." if len(url) > 50 else url

                                       
        sub_line = f"\n{status_icon} *{status_text}* | ID: `{sub_id}`\n"
        sub_line += f"📦 {title}\n"
        sub_line += f"💰 {price_text} | 🔔 {next_notify}\n"
        
                                                               
        if price_alert is not None:
            sub_line += f"🎯 {t(user_id, 'price_alert_label')}: {price_alert:.0f} TL\n"
        
        lines.append(sub_line)
        
                                                           
        inline_buttons.append([
            InlineKeyboardButton(
                text=f"⚙️ {t(user_id, 'btn_edit')} ID {sub_id}",
                callback_data=f"edit_sub:{sub_id}"
            )
        ])
    
                           
    full_text = "\n".join(lines)

                                                            
    if len(full_text) > 4000:
                                                            
        warning_msg = f"⚠️ У вас {len(subs)} подписок. Показываю первые 10:\n\n"
        short_lines = lines[:11]                    
        short_text = "\n".join(short_lines)
        short_keyboard = InlineKeyboardMarkup(inline_keyboard=inline_buttons[:10])

        await message.answer(warning_msg + short_text, reply_markup=short_keyboard, parse_mode="Markdown")
        return

                                   
    keyboard = InlineKeyboardMarkup(inline_keyboard=inline_buttons)

    try:
        await message.answer(full_text, reply_markup=keyboard, parse_mode="Markdown")
    except Exception as e:
        logger.exception("Error sending mysubs list: %s", e)
                               
        full_text_plain = full_text.replace("*", "").replace("`", "")
        await message.answer(full_text_plain, reply_markup=keyboard)

              
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

@dp.message(_filter_recommend)
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

@dp.message(_filter_trending)
async def cmd_trending(message: types.Message):
    await message.answer(t(message.from_user.id, "trending_header"), reply_markup=trending_menu_kb(message.from_user.id))

                                  
async def _filter_trending_search(message: types.Message) -> bool:
    """Filter for trending search text input"""
    if not message.text or message.text.startswith("/"):
        return False
    if not message.from_user or message.from_user.id not in TREND_SEARCH_AWAIT:
        return False
    return True

@dp.message(_filter_trending_search)
async def trending_search_text(message: types.Message):
    user_id = message.from_user.id
    q = (message.text or "").strip()
    if not q:
        await message.answer(t(user_id, "trending_enter_query"))
        return
                   
    if user_id in TREND_SEARCH_AWAIT:
        TREND_SEARCH_AWAIT.remove(user_id)
    try:
        await message.answer(t(user_id, "trending_searching"))
        items = await get_trending_by_search_top3_async(q)
        await send_trending_list(user_id, items)
    except Exception as e:
        logger.exception("trending search error: %s", e)
        await message.answer(t(user_id, "trending_no_results"))

                        
def _filter_unsubscribe(message: types.Message) -> bool:
    if not message.text or not message.from_user:
        return False
    user_id = message.from_user.id
    unsubscribe_btn = t(user_id, "btn_unsubscribe")
    return unsubscribe_btn == message.text or "отпис" in message.text.lower()

                     
@dp.message(_filter_unsubscribe)
async def cmd_unsubscribe_all(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅", callback_data="confirm_unsub_all:yes"),
        InlineKeyboardButton(text="🚫", callback_data="confirm_unsub_all:no"),
    ]])
    await message.answer(t(message.from_user.id, "btn_unsubscribe") + " ❓", reply_markup=kb)

                   
scheduler = AsyncIOScheduler()


async def send_grouped_notifications(grouped_notifications: Dict[int, List[Tuple[str, Optional[str]]]]) -> None:
    """
    Отправляет групповые уведомления пользователям с защитой от race conditions.
    grouped_notifications: user_id -> [(notification_text, image_url), ...]
    """
                                                         
    async with scheduler_lock:
        for user_id, notifications in grouped_notifications.items():
            try:
                if len(notifications) == 1:
                                                              
                    text, image = notifications[0]
                                                                          
                    await send_notification_with_timeout(user_id, text, image, timeout=15.0)
                else:
                                                                         
                    grouped_text = f"🔔 <b>ОБНОВЛЕНИЯ ЦЕН</b> ({len(notifications)})\n\n"

                    for i, (text, image) in enumerate(notifications[:10], 1):                           
                                                                     
                        clean_text = text.replace("💰 ", "").replace("📉 ", "").replace("📈 ", "")
                        grouped_text += f"{i}. {clean_text}\n"

                    if len(notifications) > 10:
                        grouped_text += f"\n... и ещё {len(notifications) - 10} обновлений"

                                                                      
                                                                          
                    await send_notification_with_timeout(
                        user_id,
                        grouped_text,
                        image=None,
                        timeout=15.0,
                        parse_mode="HTML",
                    )

            except Exception as e:
                logger.exception("Error sending grouped notifications to user %s: %s", user_id, e)


async def _check_all_impl(trigger: str = "scheduler") -> Dict[str, Any]:
    logger.info("Scheduler job: checking subscriptions (trigger=%s)", trigger)
    total = get_subscriptions_count()
    logger.info("Found %d subscriptions to check", total)

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
                notification_text = None

                                                            
                if price_alert is not None and price <= price_alert:
                    notification_needed = True
                    notification_text = (
                        f"🎯 Цена достигла целевого значения!\n"
                        f"Целевая цена: {price_alert:.0f} TL\n"
                        f"Текущая цена: {price:.0f} TL\n"
                        f"🔗 {url}"
                    )
                                                              
                    update_subscription_settings(sub_id, price_alert=None)
                    
                elif mode == "hourly":
                    notification_needed = True
                    notification_text = t(user_id, "hourly_msg").format(price=price, url=url)

                elif mode == "discount":
                    price_changed_percent = ((last_price - price) / last_price) * 100
                    
                    if notify_percent and abs(price_changed_percent) >= notify_percent:
                        notification_needed = True
                        if price < last_price:
                            notification_text = t(user_id, "discount_percent_decrease_msg").format(
                                old=last_price, new=price, percent=abs(price_changed_percent), url=url
                            )
                        else:
                            notification_text = t(user_id, "discount_percent_increase_msg").format(
                                old=last_price, new=price, percent=price_changed_percent, url=url
                            )
                    elif price < last_price:
                        notification_needed = True
                        notification_text = t(user_id, "discount_msg").format(
                            old=last_price, new=price, url=url
                        )
                
                                        
                if min_price is not None and price < min_price:
                    notification_needed = True
                    notification_text = t(user_id, "price_below_min_msg").format(
                        price=price, min_price=min_price, url=url
                    )
                elif max_price is not None and price > max_price:
                    notification_needed = True
                    notification_text = t(user_id, "price_above_max_msg").format(
                        price=price, max_price=max_price, url=url
                    )

                if notification_needed and notification_text:
                                                                                            
                    if user_id not in grouped_notifications:
                        grouped_notifications[user_id] = []
                    grouped_notifications[user_id].append((notification_text, image))

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
        return {"status": "skipped", "trigger": trigger, "reason": "already_running"}

    async with check_all_lock:
        started_at = time.time()
        try:
            result = await _check_all_impl(trigger=trigger)
            result["duration_sec"] = round(time.time() - started_at, 2)
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
        except Exception:
            logger.exception("Failed to start scheduler or add job")

                     
def is_admin(user_id: int) -> bool:
    """Check if user is admin"""
    from config import ADMIN_IDS
    result = user_id in ADMIN_IDS
    logger.debug(f"is_admin check: user_id={user_id}, ADMIN_IDS={ADMIN_IDS}, result={result}")
    return result

def _get_request_user_id(message: types.Message) -> int:
    """Resolve the real user id from a message (supports callback context)."""
    if message is None:
        return 0
    try:
        chat_id = getattr(getattr(message, "chat", None), "id", None)
        if chat_id:
            return chat_id
    except Exception:
        pass
    try:
        return getattr(getattr(message, "from_user", None), "id", 0) or 0
    except Exception:
        return 0

async def admin_main_menu(message: types.Message):
    """Показать главное меню администратора"""
    user_id = _get_request_user_id(message)
    if not is_admin(user_id):
        await message.answer(t(user_id, "admin_access_denied"))
        return

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats"),
            InlineKeyboardButton(text="👥 Пользователи", callback_data="admin_users")
        ],
        [
            InlineKeyboardButton(text="🚫 Блокировки", callback_data="admin_check_blocked"),
            InlineKeyboardButton(text="🎯 Рекомендации", callback_data="admin_recommend")
        ],
        [
            InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast_menu"),
            InlineKeyboardButton(text="🧹 Очистка", callback_data="admin_cleanup")
        ],
        [
            InlineKeyboardButton(text="💾 Бэкап", callback_data="admin_backup"),
            InlineKeyboardButton(text="📚 Справка", callback_data="admin_help")
        ]
    ])

    welcome_text = "🚀 <b>Панель администратора</b>\n\n"
    welcome_text += f"👋 Добро пожаловать, <code>{user_id}</code>!\n\n"
    welcome_text += "Выберите действие из меню ниже или используйте текстовые команды.\n\n"
    welcome_text += "<b>⚠️ Важно:</b> Все действия логируются для безопасности."

    await message.answer(welcome_text, reply_markup=keyboard, parse_mode="HTML")

async def cmd_admin(message: types.Message):
    """Admin commands handler"""
    user_id = message.from_user.id
    logger.info(f"cmd_admin called by user_id={user_id}, message='{message.text}'")
    if not is_admin(user_id):
        logger.warning(f"Access denied for user_id={user_id} in cmd_admin")
        await message.answer(t(user_id, "admin_access_denied"))
        return

    args = message.text.split()
    if len(args) < 2:
                                                        
        await admin_main_menu(message)
        return

    command = args[1].lower()

    if command == "stats":
        await admin_stats(message)
    elif command == "broadcast":
        if len(args) < 3:
            await message.answer("❌ Укажите сообщение: /admin broadcast &lt;сообщение&gt;")
            return
        await admin_broadcast(message, " ".join(args[2:]))
    elif command == "users":
        await admin_users(message)
    elif command == "cleanup":
        await admin_cleanup(message)
    elif command == "backup":
        await admin_backup(message)
    elif command == "respond":
        await admin_respond(message)
    elif command == "recommend":
        await admin_recommend(message, args[2:] if len(args) > 2 else [])
    elif command == "blocked":
        await admin_check_blocked(message)
    else:
        await message.answer(t(user_id, "admin_unknown_command"))

async def admin_stats(message: types.Message):
    """Show comprehensive bot statistics"""
    try:
                                       
        report = Analytics.get_full_report()

                                                                 
        if len(report) > 4000:
                                
            parts = []
            current_part = ""

            for line in report.split('\n'):
                if len(current_part + line + '\n') > 3500:
                    parts.append(current_part)
                    current_part = line + '\n'
                else:
                    current_part += line + '\n'

            if current_part:
                parts.append(current_part)

                                  
            for i, part in enumerate(parts[:3]):                        
                await message.answer(part, parse_mode="HTML")
                if i < len(parts) - 1:
                    await asyncio.sleep(0.5)                                     
        else:
            await message.answer(report, parse_mode="HTML")

    except Exception as e:
        logger.exception("Error in admin_stats: %s", e)
        await message.answer(f"❌ Ошибка при получении статистики: {e}")

async def admin_broadcast(message: types.Message, text: str):
    """Broadcast message to all users"""
    try:
        import sqlite3

        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()

        cursor.execute("SELECT user_id FROM users")
        users = cursor.fetchall()
        conn.close()

        sent_count = 0
        failed_count = 0

        status_msg = await message.answer("📤 Начинаю рассылку...")

        for (user_id,) in users:
            try:
                await bot.send_message(user_id, f"📢 <b>ОБЪЯВЛЕНИЕ</b>\n\n{text}", parse_mode="HTML")
                sent_count += 1

                                              
                if sent_count % 10 == 0:
                    await status_msg.edit_text(f"📤 Отправлено: {sent_count}/{len(users)}")

                                                  
                await asyncio.sleep(0.1)

            except Exception as e:
                logger.warning(f"Failed to send broadcast to {user_id}: {e}")
                failed_count += 1

        await status_msg.edit_text(
            f"✅ <b>Рассылка завершена!</b>\n\n"
            f"📤 Отправлено: {sent_count}\n"
            f"❌ Не доставлено: {failed_count}",
            parse_mode="HTML"
        )

    except Exception as e:
        logger.exception("Error in admin_broadcast: %s", e)
        await message.answer(f"❌ Ошибка при рассылке: {e}")

async def admin_users(message: types.Message):
    """Show list of active users or detailed info about specific user"""
    try:
        from database import get_connection

                                 
        args = message.text.split()
        target_user_id = None

        if len(args) > 2 and args[1] == "users" and args[2].isdigit():
            target_user_id = int(args[2])

        if target_user_id:
                                                    
            await admin_user_details(message, target_user_id)
        else:
                                                
            await admin_users_list(message)

    except Exception as e:
        logger.exception("Error in admin_users: %s", e)
        await message.answer(f"❌ {t(message.from_user.id, 'error_generic')}: {e}")

async def admin_users_list(message: types.Message):
    """Show list of active users"""
    try:
        from database import get_connection

        admin_user_id = _get_request_user_id(message)

        with get_connection() as conn:
            cursor = conn.cursor()

                                                         
            cursor.execute("PRAGMA table_info(users)")
            columns = cursor.fetchall()
            column_names = [col[1] for col in columns]

            if 'created_at' in column_names:
                                                        
                query = """
                    SELECT u.user_id, u.language, u.created_at, COUNT(s.id) as subs_count
                    FROM users u
                    LEFT JOIN subscriptions s ON u.user_id = s.user_id
                    GROUP BY u.user_id, u.language, u.created_at
                    ORDER BY u.created_at DESC
                    LIMIT 50
                """
            else:
                                                                    
                query = """
                    SELECT u.user_id, u.language, COUNT(s.id) as subs_count
                    FROM users u
                    LEFT JOIN subscriptions s ON u.user_id = s.user_id
                    GROUP BY u.user_id, u.language
                    ORDER BY u.user_id DESC
                    LIMIT 50
                """

            cursor.execute(query)
            users = cursor.fetchall()

        if not users:
            await message.answer(t(message.from_user.id, "admin_users_none"))
            return

                                                  
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

        keyboard = InlineKeyboardMarkup(inline_keyboard=[])
        users_text = f"👥 <b>{t(admin_user_id, 'admin_users_title')}</b>\n\n"

        for user_data in users:
            if len(user_data) == 4:
                                       
                user_id, language, created_at, subs_count = user_data
                created_str = datetime.fromtimestamp(created_at).strftime('%d.%m.%Y %H:%M')
                user_line = f"🆔 <code>{user_id}</code> | 🌐 {language.upper()} | 📦 {subs_count} | 📅 {created_str}"
            else:
                                        
                user_id, language, subs_count = user_data
                user_line = f"🆔 <code>{user_id}</code> | 🌐 {language.upper()} | 📦 {subs_count}"

            users_text += user_line + "\n"

                                      
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(
                    text=f"📋 {t(admin_user_id, 'admin_user_details_btn')} (ID: {user_id})",
                    callback_data=f"user_details:{user_id}"
                )
            ])

        users_text += f"\n💡 {t(admin_user_id, 'admin_users_interactive_hint')}"

        await message.answer(users_text, reply_markup=keyboard, parse_mode="HTML")

    except Exception as e:
        logger.exception("Error in admin_users_list: %s", e)
        await message.answer(f"❌ {t(message.from_user.id, 'error_generic')}: {e}")

async def admin_users_list_interactive(message: types.Message):
    """Callback version of admin_users_list for refresh functionality"""
    try:
        from database import get_connection

        admin_user_id = _get_request_user_id(message)

        with get_connection() as conn:
            cursor = conn.cursor()

                                                         
            cursor.execute("PRAGMA table_info(users)")
            columns = cursor.fetchall()
            column_names = [col[1] for col in columns]

            if 'created_at' in column_names:
                                                        
                query = """
                    SELECT u.user_id, u.language, u.created_at, COUNT(s.id) as subs_count
                    FROM users u
                    LEFT JOIN subscriptions s ON u.user_id = s.user_id
                    GROUP BY u.user_id, u.language, u.created_at
                    ORDER BY u.created_at DESC
                    LIMIT 50
                """
            else:
                                                                    
                query = """
                    SELECT u.user_id, u.language, COUNT(s.id) as subs_count
                    FROM users u
                    LEFT JOIN subscriptions s ON u.user_id = s.user_id
                    GROUP BY u.user_id, u.language
                    ORDER BY u.user_id DESC
                    LIMIT 50
                """

            cursor.execute(query)
            users = cursor.fetchall()

        if not users:
            await message.edit_text(t(admin_user_id, "admin_users_none"))
            return

                                                  
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

                                               
        users_text = "👥 <b>Управление пользователями</b>\n\n"
        users_text += f"📊 <b>Всего пользователей:</b> {len(users)}\n\n"

        keyboard = InlineKeyboardMarkup(inline_keyboard=[])

                                                                                
        active_users = [u for u in users if (u[3] if len(u) == 4 else u[2]) > 0]
        inactive_users = [u for u in users if (u[3] if len(u) == 4 else u[2]) == 0]

        def _safe_user_button(user_id_raw, subs_count, inactive: bool = False):
            try:
                user_id_int = int(user_id_raw)
                if user_id_int <= 0:
                    return None
            except Exception:
                return None
            if inactive:
                text = f"👤 {user_id_int} (неактивен)"
            else:
                text = f"👤 {user_id_int} ({subs_count} подписок)"
                if subs_count > 5:
                    text += " ⭐"
                                                                      
            if len(text) > 64:
                text = text[:61] + "..."
            cb = f"user_details:{user_id_int}"
            if len(cb) > 64:
                return None
            return InlineKeyboardButton(text=text, callback_data=cb)

        if active_users:
            users_text += "🟢 <b>Активные пользователи:</b>\n"
            for user_data in active_users[:15]:                                   
                if len(user_data) == 4:
                    user_id, language, created_at, subs_count = user_data
                    created_str = datetime.fromtimestamp(created_at).strftime('%d.%m.%Y')
                    users_text += f"  👤 <code>{user_id}</code> | 🌐 {language.upper()} | 📦 {subs_count} | 📅 {created_str}\n"
                else:
                    user_id, language, subs_count = user_data
                    users_text += f"  👤 <code>{user_id}</code> | 🌐 {language.upper()} | 📦 {subs_count}\n"

                                                                          
                button = _safe_user_button(user_id, subs_count, inactive=False)
                if button:
                    keyboard.inline_keyboard.append([button])

        if inactive_users and len(keyboard.inline_keyboard) < 10:                                           
            users_text += "\n🟡 <b>Неактивные пользователи:</b>\n"
            for user_data in inactive_users[:5]:                         
                if len(user_data) == 4:
                    user_id, language, created_at, subs_count = user_data
                    created_str = datetime.fromtimestamp(created_at).strftime('%d.%m.%Y')
                    users_text += f"  👤 <code>{user_id}</code> | 🌐 {language.upper()} | 📅 {created_str}\n"
                else:
                    user_id, language, subs_count = user_data
                    users_text += f"  👤 <code>{user_id}</code> | 🌐 {language.upper()}\n"

                button = _safe_user_button(user_id, subs_count, inactive=True)
                if button:
                    keyboard.inline_keyboard.append([button])

                                                       
        control_rows = [
            [
                InlineKeyboardButton(text="🔄 Обновить", callback_data="admin_users_refresh"),
                InlineKeyboardButton(text="🚫 Проверить блокировки", callback_data="admin_check_blocked")
            ],
            [
                InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats_refresh"),
                InlineKeyboardButton(text="🏠 Главное меню", callback_data="admin_main_menu")
            ]
        ]
        keyboard.inline_keyboard.extend(control_rows)

        try:
            await message.edit_text(users_text, reply_markup=keyboard, parse_mode="HTML")
        except Exception as e:
                                                                                    
                                                                       
            if "BUTTON_USER_INVALID" in str(e):
                from aiogram.types import InlineKeyboardMarkup
                fallback_text = users_text + "\n\n💡 Для деталей: /admin users <id>"
                fallback_kb = InlineKeyboardMarkup(inline_keyboard=control_rows)
                await message.edit_text(fallback_text, reply_markup=fallback_kb, parse_mode="HTML")
                return
            raise

    except Exception as e:
        logger.exception("Error in admin_users_list_callback: %s", e)
        await message.edit_text(f"❌ {t(admin_user_id, 'error_generic')}: {e}")

    except Exception as e:
        logger.exception("Error in admin_users_list_interactive: %s", e)
        await message.answer(f"❌ {t(admin_user_id, 'error_generic')}: {e}")

async def admin_user_details(message: types.Message, target_user_id: int):
    """Show detailed information about specific user"""
    try:
        from database import get_connection, get_user_subscriptions

        with get_connection() as conn:
            cursor = conn.cursor()

                                               
            cursor.execute("PRAGMA table_info(users)")
            columns = cursor.fetchall()
            column_names = [col[1] for col in columns]
            has_created_at = 'created_at' in column_names

                                 
            if has_created_at:
                cursor.execute("""
                    SELECT user_id, language, notify_quiet_hours_start, notify_quiet_hours_end, created_at
                    FROM users
                    WHERE user_id = ?
                """, (target_user_id,))
            else:
                cursor.execute("""
                    SELECT user_id, language, notify_quiet_hours_start, notify_quiet_hours_end, 0 as created_at
                    FROM users
                    WHERE user_id = ?
                """, (target_user_id,))

            user_data = cursor.fetchone()

            if not user_data:
                await message.answer(f"❌ {t(message.from_user.id, 'admin_user_not_found')}")
                return

            user_id, language, quiet_start, quiet_end, created_at = user_data

                                      
            subscriptions = get_user_subscriptions(user_id)

                                      
            user_text = f"👤 <b>{t(message.from_user.id, 'admin_user_details_title')}</b>\n\n"
            user_text += f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
            user_text += f"🌐 <b>{t(message.from_user.id, 'language')}:</b> {language.upper()}\n"

            if created_at > 0:
                created_str = datetime.fromtimestamp(created_at).strftime('%d.%m.%Y %H:%M')
                user_text += f"📅 <b>{t(message.from_user.id, 'admin_user_registered')}:</b> {created_str}\n"

            user_text += f"📦 <b>{t(message.from_user.id, 'admin_user_subscriptions')}:</b> {len(subscriptions)}\n"

            if quiet_start is not None and quiet_end is not None:
                user_text += f"🔔 <b>{t(message.from_user.id, 'admin_user_quiet_hours')}:</b> {quiet_start:02d}:00 - {quiet_end:02d}:00\n"

            user_text += "\n"

                                       
            if subscriptions:
                user_text += f"📋 <b>{t(message.from_user.id, 'admin_user_subs_list')}:</b>\n\n"

                for i, sub in enumerate(subscriptions[:10], 1):                             
                    try:
                        (sub_id, _, url, mode, last_price, product_title, product_image,
                         min_price, max_price, notify_percent, notify_interval, last_notify_time, price_alert, tags) = sub
                    except ValueError:
                        (sub_id, _, url, mode, last_price, product_title, product_image,
                         min_price, max_price, notify_percent, notify_interval, last_notify_time) = sub[:12]
                        price_alert = None
                        tags = None

                    title = product_title if product_title else url[:50] + "..." if len(url) > 50 else url
                    status = "✅" if last_price else "⚠️"
                    price_str = f"{last_price:.0f} TL" if last_price else t(message.from_user.id, "unknown_price")

                    user_text += f"{i}. {status} <code>{sub_id}</code> - {title}\n"
                    user_text += f"   💰 {price_str} | 🔔 {t(message.from_user.id, f'mode_{mode}')}\n"

                    if price_alert:
                        user_text += f"   🎯 {t(message.from_user.id, 'price_alert_label')}: {price_alert:.0f} TL\n"

                    user_text += "\n"

                if len(subscriptions) > 10:
                    user_text += f"... {t(message.from_user.id, 'admin_user_more_subs').format(more=len(subscriptions)-10)}\n"
            else:
                user_text += f"📝 {t(message.from_user.id, 'admin_user_no_subs')}\n"

                                                                  
        if len(user_text) > 4000:
            parts = []
            current_part = ""

            for line in user_text.split('\n'):
                if len(current_part + line + '\n') > 3500:
                    parts.append(current_part)
                    current_part = line + '\n'
                else:
                    current_part += line + '\n'

            if current_part:
                parts.append(current_part)

                           
            for i, part in enumerate(parts):
                await message.answer(part, parse_mode="HTML")
                if i < len(parts) - 1:
                    await asyncio.sleep(0.5)
        else:
            await message.answer(user_text, parse_mode="HTML")

    except Exception as e:
        logger.exception("Error in admin_user_details: %s", e)
        await message.answer(f"❌ {t(message.from_user.id, 'error_generic')}: {e}")

async def admin_user_details_callback(message: types.Message, target_user_id: int, admin_user_id: int):
    """Callback version of admin_user_details for interactive interface"""
    try:
        from database import get_connection, get_user_subscriptions

        with get_connection() as conn:
            cursor = conn.cursor()

                                               
            cursor.execute("PRAGMA table_info(users)")
            columns = cursor.fetchall()
            column_names = [col[1] for col in columns]
            has_created_at = 'created_at' in column_names

                                 
            if has_created_at:
                cursor.execute("""
                    SELECT user_id, language, notify_quiet_hours_start, notify_quiet_hours_end, created_at
                    FROM users
                    WHERE user_id = ?
                """, (target_user_id,))
            else:
                cursor.execute("""
                    SELECT user_id, language, notify_quiet_hours_start, notify_quiet_hours_end, 0 as created_at
                    FROM users
                    WHERE user_id = ?
                """, (target_user_id,))

            user_data = cursor.fetchone()

            if not user_data:
                await message.edit_text(f"❌ {t(admin_user_id, 'admin_user_not_found')}")
                return

            user_id, language, quiet_start, quiet_end, created_at = user_data

                                           
            telegram_user_info = ""
            try:
                                                                                           
                chat_member = await bot.get_chat_member(chat_id=target_user_id, user_id=target_user_id)
                telegram_user = chat_member.user

                                 
                full_name = ""
                if telegram_user.first_name:
                    full_name = telegram_user.first_name
                if telegram_user.last_name:
                    full_name += f" {telegram_user.last_name}"
                full_name = full_name.strip() or "Неизвестно"

                          
                username = f"@{telegram_user.username}" if telegram_user.username else "Не установлен"

                                
                premium_status = "⭐ Да" if getattr(telegram_user, 'is_premium', False) else "Обычный"

                                        
                telegram_lang = getattr(telegram_user, 'language_code', 'Неизвестно')

                telegram_user_info = f"""
👨‍💼 <b>Имя:</b> {full_name}
📱 <b>Username:</b> {username}
🌐 <b>Язык Telegram:</b> {telegram_lang}
⭐ <b>Премиум:</b> {premium_status}"""

            except Exception as e:
                logger.warning(f"Could not get Telegram user info for {target_user_id}: {e}")
                telegram_user_info = "\n⚠️ <b>Информация из Telegram недоступна</b> (пользователь мог заблокировать бота)"

                                      
            subscriptions = get_user_subscriptions(user_id)

                                      
            user_text = f"👤 <b>{t(admin_user_id, 'admin_user_details_title')}</b>\n\n"
            user_text += f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
            user_text += f"🌐 <b>{t(admin_user_id, 'language')}:</b> {language.upper()}\n"
            user_text += f"📊 <b>{t(admin_user_id, 'admin_user_subscriptions')}:</b> {len(subscriptions)}\n"

            if created_at > 0:
                import time
                created_str = time.strftime('%d.%m.%Y %H:%M', time.localtime(created_at))
                user_text += f"📅 <b>{t(admin_user_id, 'admin_user_registered')}:</b> {created_str}\n"

            user_text += telegram_user_info

            if quiet_start is not None and quiet_end is not None:
                user_text += f"\n🕐 <b>{t(admin_user_id, 'admin_user_quiet_hours')}:</b> {quiet_start:02d}:00 - {quiet_end:02d}:00\n"
            else:
                user_text += f"\n🕐 <b>{t(admin_user_id, 'admin_user_quiet_hours')}:</b> {t(admin_user_id, 'admin_user_not_set')}\n"

            if subscriptions:
                user_text += f"\n📦 <b>{t(admin_user_id, 'admin_user_subs_list')}:</b>\n"

                for sub in subscriptions[:10]:                               
                    try:
                        (sid, uid, url, mode, last_price, product_title, product_image,
                         min_price, max_price, notify_percent, notify_interval, last_notify_time, price_alert) = sub
                    except ValueError:
                                                        
                        (sid, uid, url, mode, last_price, product_title, product_image,
                         min_price, max_price, notify_percent, notify_interval, last_notify_time) = sub[:12]
                        price_alert = None

                    title = product_title if product_title else url.split('/')[-1][:30] + "..."
                    price_str = f"{last_price:.0f} TL" if last_price is not None else t(admin_user_id, "unknown_price")
                    status = "✅" if last_price is not None else "❌"

                    user_text += f"   {status} {title} | 💰 {price_str} | 🔔 {t(admin_user_id, f'mode_{mode}')}\n"

                    if price_alert:
                        user_text += f"   🎯 {t(admin_user_id, 'price_alert_label')}: {price_alert:.0f} TL\n"

                if len(subscriptions) > 10:
                    user_text += f"... {t(admin_user_id, 'admin_user_more_subs').format(more=len(subscriptions)-10)}\n"
            else:
                user_text += f"\n📝 {t(admin_user_id, 'admin_user_no_subs')}\n"

                                      
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

        keyboard = InlineKeyboardMarkup(inline_keyboard=[])
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(
                text=f"💬 {t(admin_user_id, 'admin_user_message')}",
                url=f"tg://user?id={target_user_id}"
            ),
            InlineKeyboardButton(
                text=f"🔙 {t(admin_user_id, 'btn_back')}",
                callback_data="admin_users_refresh"
            )
        ])

                                                                  
        if len(user_text) > 4000:
            parts = []
            current_part = ""

            for line in user_text.split('\n'):
                if len(current_part + line + '\n') > 3500:
                    parts.append(current_part)
                    current_part = line + '\n'
                else:
                    current_part += line + '\n'

            if current_part:
                parts.append(current_part)

                           
            for i, part in enumerate(parts):
                if i == 0:
                    await message.edit_text(part, parse_mode="HTML")
                else:
                    await message.answer(part, parse_mode="HTML")
                    await asyncio.sleep(0.5)

                                               
            await message.answer(f"🔧 <b>Действия с пользователем {target_user_id}:</b>", reply_markup=keyboard, parse_mode="HTML")
        else:
            await message.edit_text(user_text, reply_markup=keyboard, parse_mode="HTML")

    except Exception as e:
        logger.exception("Error in admin_user_details_callback: %s", e)
        await message.edit_text(f"❌ {t(admin_user_id, 'error_generic')}: {e}")

async def admin_cleanup(message: types.Message):
    """Clean up old/inactive data"""
    try:
        import sqlite3

        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()

                              
        cursor.execute("SELECT COUNT(*) FROM price_history WHERE ts < ?", (int(time.time()) - 30*24*3600,))
        old_price_points = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM users WHERE user_id NOT IN (SELECT DISTINCT user_id FROM subscriptions)")
        inactive_users = cursor.fetchone()[0]

                                                        
        cursor.execute("DELETE FROM price_history WHERE ts < ?", (int(time.time()) - 30*24*3600,))

                                                                  
        cursor.execute("""
            DELETE FROM users
            WHERE user_id NOT IN (SELECT DISTINCT user_id FROM subscriptions)
            AND created_at < ?
        """, (int(time.time()) - 90*24*3600,))

        conn.commit()
        conn.close()

        cleanup_text = f"""
🧹 <b>ОЧИСТКА ЗАВЕРШЕНА</b>

🗂️ <b>Удалено:</b>
• Старых точек цены (>30 дней): {old_price_points}
• Неактивных пользователей (>90 дней): {inactive_users}

💾 <b>База данных оптимизирована</b>
"""

        await message.answer(cleanup_text, parse_mode="HTML")

    except Exception as e:
        logger.exception("Error in admin_cleanup: %s", e)
        await message.answer(f"❌ Ошибка при очистке: {e}")


def _prune_old_backups(backups_dir: Path, keep_last: int) -> int:
    """Remove old db backups and return number of retained files."""
    backup_files = list(backups_dir.glob("db_backup_*.db"))
    backup_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)

    if len(backup_files) > keep_last:
        for old_file in backup_files[keep_last:]:
            try:
                old_file.unlink()
            except Exception:
                logger.warning("Failed to remove old backup file: %s", old_file, exc_info=True)

    return min(len(backup_files), keep_last)


async def _create_database_backup(trigger: str) -> Dict[str, Any]:
    """Create backup and apply retention policy."""
    timestamp = int(time.time())
    backups_dir = Path("backups")
    backups_dir.mkdir(exist_ok=True)

    backup_path = backups_dir / f"db_backup_{timestamp}.db"
    await asyncio.to_thread(create_sqlite_backup, str(backup_path))

    retained = _prune_old_backups(backups_dir, DB_BACKUP_KEEP_FILES)
    size_mb = backup_path.stat().st_size / 1024 / 1024

    logger.info(
        "Database backup created (trigger=%s): %s, size=%.2fMB, retained=%d",
        trigger,
        backup_path,
        size_mb,
        retained,
    )
    return {"path": str(backup_path), "size_mb": size_mb, "retained": retained}


async def admin_backup(message: types.Message):
    """Manual database backup"""
    try:
        result = await _create_database_backup(trigger="admin")

        await message.answer(
            f"✅ <b>БЭКАП СОЗДАН</b>\n\n"
            f"📁 Файл: {result['path']}\n"
            f"📊 Размер: {result['size_mb']:.1f} MB\n"
            f"🗂️ Храним бэкапов: {result['retained']}",
            parse_mode="HTML"
        )

    except Exception as e:
        logger.exception("Error in admin_backup: %s", e)
        await message.answer(f"❌ Ошибка при создании бэкапа: {e}")

async def submit_user_report(user_id: int, report_text: str, message: types.Message):
    """Submit user report to admin"""
    try:
                                     
        from database import get_connection
        user_lang = "ru"
        user_created = None
        with get_connection() as conn:
            cursor = conn.cursor()
                                               
            cursor.execute("PRAGMA table_info(users)")
            columns = cursor.fetchall()
            column_names = [col[1] for col in columns]

            if 'created_at' in column_names:
                cursor.execute("SELECT language, created_at FROM users WHERE user_id = ?", (user_id,))
                user_data = cursor.fetchone()
                if user_data:
                    user_lang = user_data[0] or "ru"
                    user_created = user_data[1]
            else:
                cursor.execute("SELECT language FROM users WHERE user_id = ?", (user_id,))
                user_data = cursor.fetchone()
                if user_data:
                    user_lang = user_data[0] or "ru"

                                     
        subs_count = len(get_user_subscriptions(user_id))

                                              
        user_info = ""
        if message and message.from_user:
            user = message.from_user

                             
            full_name = ""
            if user.first_name:
                full_name = user.first_name
            if user.last_name:
                full_name += f" {user.last_name}"
            full_name = full_name.strip() or "Не указано"

                      
            username = f"@{user.username}" if user.username else "Не установлен"

                            
            premium_status = "⭐ Да" if getattr(user, 'is_premium', False) else "Обычный"

                                    
            telegram_lang = getattr(user, 'language_code', 'Неизвестно')

                               
            created_date = "Неизвестно"
            if user_created:
                import time
                created_date = time.strftime('%Y-%m-%d %H:%M', time.localtime(user_created))

            user_info = f"""
👨‍💼 <b>Имя:</b> {full_name}
📱 <b>Username:</b> {username}
🌐 <b>Язык Telegram:</b> {telegram_lang}
⭐ <b>Премиум:</b> {premium_status}
📅 <b>Регистрация:</b> {created_date}"""

                                 
        admin_report = f"""
📋 <b>НОВЫЙ РЕПОРТ ОТ ПОЛЬЗОВАТЕЛЯ</b>

👤 <b>ID:</b> <code>{user_id}</code>
🌐 <b>Язык бота:</b> {user_lang}
📊 <b>Подписок:</b> {subs_count}{user_info}

💬 <b>Сообщение:</b>
{report_text}

<i>Используйте /admin respond {user_id} [текст ответа] для ответа</i>
"""

                            
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(admin_id, admin_report, parse_mode="HTML")
            except Exception as e:
                logger.warning(f"Failed to send report to admin {admin_id}: {e}")

                                                      
        if message:
            await message.answer(t(user_id, "report_sent"))

    except Exception as e:
        logger.exception("Error submitting user report: %s", e)
        if message and hasattr(message, 'answer'):
            try:
                await message.answer(t(user_id, "error_generic"))
            except Exception:
                pass                                             

async def admin_respond(message: types.Message):
    """Admin command to respond to user reports"""
    try:
        if message.from_user.id not in ADMIN_IDS:
            await message.answer("❌ У вас нет прав администратора")
            return

        parts = message.text.split(maxsplit=2)
        if len(parts) < 3:
            await message.answer("❌ Использование: /admin respond <user_id> <текст ответа>")
            return

        target_user_id = int(parts[1])
        response_text = parts[2]

                               
        try:
            response_message = f"""
💬 <b>ОТВЕТ АДМИНИСТРАТОРА</b>

{response_text}

<i>Если у вас есть дополнительные вопросы, используйте /report</i>
"""
            await bot.send_message(target_user_id, response_message, parse_mode="HTML")

                              
            await message.answer(f"✅ Ответ отправлен пользователю {target_user_id}")

        except Exception as e:
            logger.warning(f"Failed to send response to user {target_user_id}: {e}")
            await message.answer(f"❌ Не удалось отправить ответ пользователю {target_user_id}")

    except ValueError:
        await message.answer("❌ Неверный формат user_id")
    except Exception as e:
        logger.exception("Error in admin_respond: %s", e)
        await message.answer(f"❌ Ошибка: {e}")

async def admin_recommend(message: types.Message, args: List[str]):
    """Управление рекомендуемыми продуктами для рекламы"""
    user_id = message.from_user.id

    if not args:
                                                          
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="📋 Список товаров", callback_data="admin_recommend_list"),
                InlineKeyboardButton(text="➕ Добавить товар", callback_data="admin_recommend_add"),
            ],
            [
                InlineKeyboardButton(text="🗑️ Удалить товар", callback_data="admin_recommend_remove"),
                InlineKeyboardButton(text="⭐ Изменить приоритет", callback_data="admin_recommend_priority"),
            ],
            [
                InlineKeyboardButton(text="✏️ Текст", callback_data="admin_recommend_text"),
                InlineKeyboardButton(text="📚 Справка", callback_data="admin_recommend_help"),
            ]
        ])

        await message.answer(
            "🎯 <b>Управление рекомендуемыми продуктами</b>\n\n"
            "Выберите действие или используйте команды:\n"
            "<code>/admin recommend list</code> - список товаров\n"
            "<code>/admin recommend add \"Название\" \"URL\"</code> - добавить\n"
            "<code>/admin recommend remove ID</code> - удалить\n"
            "<code>/admin recommend priority ID приоритет</code> - приоритет\n"
            "<code>/admin recommend text ТЕКСТ</code> - текст кнопки рекомендаций",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        return

    subcommand = args[0].lower()

    try:
        from database import (
            get_recommended_products,
            add_recommended_product,
            remove_recommended_product,
            update_recommended_product_priority
        )

        if subcommand == "list":
            await _admin_recommend_list(message)

        elif subcommand == "add":
            if len(args) < 3:
                await message.answer(
                    "❌ <b>Неверный формат</b>\n\n"
                    "Использование:\n"
                    "<code>/admin recommend add \"Название товара\" \"https://ссылка\" [цена] [категория] [бренд]</code>\n\n"
                    "Пример:\n"
                    "<code>/admin recommend add \"iPhone 15 Pro\" \"https://trendyol.com/iphone-p-123\" \"₺45,000\" smartphones apple</code>",
                    parse_mode="HTML"
                )
                return

            title = args[1]
            url = args[2]
            price = args[3] if len(args) > 3 else ""
            category = args[4] if len(args) > 4 else ""
            brand = args[5] if len(args) > 5 else ""
            reason = " ".join(args[6:]) if len(args) > 6 else "Рекомендуемый товар"

            if add_recommended_product(title, url, price, category, brand, reason):
                                                                     
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="📋 Посмотреть список", callback_data="admin_recommend_list")]
                ])
                await message.answer(
                    f"✅ <b>Продукт успешно добавлен!</b>\n\n"
                    f"📦 <b>{title}</b>\n"
                    f"💰 {price or 'Цена не указана'}\n"
                    f"🎯 {category or 'Категория не указана'}\n"
                    f"🏷️ {brand or 'Бренд не указан'}",
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
            else:
                await message.answer("❌ Ошибка при добавлении продукта")

        elif subcommand == "remove":
            if len(args) < 2:
                await message.answer("❌ Укажите ID продукта для удаления")
                return

            try:
                product_id = int(args[1])
                if remove_recommended_product(product_id):
                    keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="📋 Посмотреть список", callback_data="admin_recommend_list")]
                    ])
                    await message.answer(
                        f"✅ Продукт #{product_id} успешно удален",
                        reply_markup=keyboard
                    )
                else:
                    await message.answer(f"❌ Продукт #{product_id} не найден")
            except ValueError:
                await message.answer("❌ ID должен быть числом")

        elif subcommand == "priority":
            if len(args) < 3:
                await message.answer(
                    "❌ <b>Неверный формат</b>\n\n"
                    "Использование: <code>/admin recommend priority ID приоритет</code>\n"
                    "Пример: <code>/admin recommend priority 5 10</code>",
                    parse_mode="HTML"
                )
                return

            try:
                product_id = int(args[1])
                priority = int(args[2])

                if update_recommended_product_priority(product_id, priority):
                    await message.answer(
                        f"✅ Приоритет продукта #{product_id} изменен на {priority}\n\n"
                        f"{'⭐' * min(priority, 5)} (приоритет {priority})"
                    )
                else:
                    await message.answer(f"❌ Продукт #{product_id} не найден")
            except ValueError:
                await message.answer("❌ ID и приоритет должны быть числами")

        elif subcommand == "text":
            lang = get_user_language(user_id)
            raw_text = message.text or ""
            prefix = "/admin recommend text"
            new_text = ""
            if raw_text.lower().startswith(prefix):
                new_text = raw_text[len(prefix):].strip()
            else:
                new_text = " ".join(args[1:]).strip()

            if not new_text:
                current = get_bot_text("recommend_text", lang)
                if current:
                    preview = html.escape(current)
                    await message.answer(
                        "✏️ <b>Текст рекомендаций</b>\n\n"
                        "Текущий текст:\n"
                        f"<code>{preview}</code>\n\n"
                        "Обновить:\n"
                        "<code>/admin recommend text ...</code>\n\n"
                        "Очистить:\n"
                        "<code>/admin recommend text clear</code>\n\n"
                        "Поддерживается HTML: <b>, <i>, <code>, <a href=\"...\">...</a>",
                        parse_mode="HTML",
                        disable_web_page_preview=True,
                    )
                else:
                    await message.answer(
                        "✏️ <b>Текст рекомендаций</b>\n\n"
                        "Текст не задан.\n\n"
                        "Установить:\n"
                        "<code>/admin recommend text ...</code>\n\n"
                        "Очистить:\n"
                        "<code>/admin recommend text clear</code>\n\n"
                        "Поддерживается HTML: <b>, <i>, <code>, <a href=\"...\">...</a>",
                        parse_mode="HTML",
                        disable_web_page_preview=True,
                    )
                return

            if new_text.lower() in ("clear", "reset", "default", "off"):
                set_bot_text("recommend_text", "", lang)
                await message.answer("✅ Текст рекомендаций очищен. Будет использоваться стандартный.")
                return

            set_bot_text("recommend_text", new_text, lang)
            await message.answer("✅ Текст рекомендаций обновлён.")

        else:
            await message.answer("❌ Неизвестная подкоманда. Используйте /admin recommend для меню")

    except Exception as e:
        logger.exception(f"Error in admin_recommend: {e}")
        await message.answer(f"❌ Ошибка: {e}")

async def _admin_recommend_list(message: types.Message):
    """Показать список рекомендуемых продуктов с красивым форматированием"""
    from database import get_recommended_products
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    products = get_recommended_products()
    if not products:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить первый товар", callback_data="admin_recommend_add")],
            [InlineKeyboardButton(text="✏️ Текст", callback_data="admin_recommend_text")]
        ])
        await message.answer(
            "📝 <b>Рекомендуемых продуктов пока нет</b>\n\n"
            "Добавьте товары для рекламы в разделе рекомендаций",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        return

    response = f"📋 <b>Рекомендуемые продукты ({len(products)})</b>\n\n"

    keyboard_buttons = []

    for i, product in enumerate(products[:10], 1):                                   
        priority_stars = "⭐" * min(product.get('priority', 0), 3)
        response += f"{i}. {priority_stars} <b>{product['title'][:30]}</b>\n"
        response += f"   💰 {product['price'] or '—'} | 🎯 {product['category'] or '—'}\n"

                                                      
        keyboard_buttons.append([
            InlineKeyboardButton(
                text=f"#{product['id']} {product['title'][:15]}...",
                callback_data=f"admin_product_{product['id']}"
            )
        ])

                                 
    keyboard_buttons.extend([
        [
            InlineKeyboardButton(text="➕ Добавить", callback_data="admin_recommend_add"),
            InlineKeyboardButton(text="✏️ Текст", callback_data="admin_recommend_text")
        ],
        [
            InlineKeyboardButton(text="📚 Справка", callback_data="admin_recommend_help")
        ]
    ])

    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

                                    
    if len(response) > 3500:
        response = response[:3400] + "\n\n... (сообщение обрезано)"

    await message.answer(response, reply_markup=keyboard, parse_mode="HTML")

                       
async def backup_database():
    """Create daily database backup"""
    try:
        result = await _create_database_backup(trigger="scheduler")
        logger.info(
            "Daily backup created: %s (%.2f MB, retained=%d)",
            result["path"],
            result["size_mb"],
            result["retained"],
        )
    except Exception as e:
        logger.exception(f"Error in automatic backup: {e}")

                                  
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

                       
@dp.message(Command("alerts"))
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

        for sub in subs:
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
                    text=f"⚙️ {t(user_id, 'btn_edit')} ID {sub_id}",
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

@dp.message(Command("import"))
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

@dp.message(Command("recommend"))
async def cmd_recommend(message: types.Message):
    """Show personalized product recommendations"""
    user_id = message.from_user.id
    add_user_if_not_exists(user_id)

    await message.answer(t(user_id, "recommend_loading"))

    try:
        lang = get_user_language(user_id)
        custom_text = get_bot_text("recommend_text", lang)
        custom_text = custom_text.strip() if custom_text else None
        recommendations = await generate_recommendations(user_id, limit=5)

        if not recommendations:
            if custom_text:
                await message.answer(custom_text, parse_mode="HTML")
            else:
                await message.answer(t(user_id, "recommend_no_data"))
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
        await message.answer(response, reply_markup=markup, parse_mode="HTML")

    except Exception as e:
        logger.exception("Error in cmd_recommend: %s", e)
        await message.answer(f"❌ {t(user_id, 'error_generic')}: {e}")

                   
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
                          
        await bot.get_me()
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

                                                                     
def _prune_legacy_handlers_for_new_mode() -> None:
    """Drop legacy handlers that conflict with the new architecture."""
    legacy_message_callbacks = {
                                                                       
        "cmd_language_command",
        "cmd_lang_message",
                                                            
        "cmd_onboarding_try",
        "cmd_onboarding_skip",
        "cmd_onboarding_done",
    }

    before_msg = len(dp.message.handlers)
    dp.message.handlers[:] = [
        h for h in dp.message.handlers
        if getattr(h.callback, "__name__", "") not in legacy_message_callbacks
    ]
    removed_msg = before_msg - len(dp.message.handlers)

    before_cb = len(dp.callback_query.handlers)
    dp.callback_query.handlers[:] = [
        h for h in dp.callback_query.handlers
        if getattr(h.callback, "__name__", "") != "callback_handler_old"
    ]
    removed_cb = before_cb - len(dp.callback_query.handlers)

    if removed_msg or removed_cb:
        logger.info(
            "Pruned legacy handlers for new mode: message=%d, callback=%d",
            removed_msg,
            removed_cb,
        )


                                         
use_new_handlers_init = USE_NEW_HANDLERS
if use_new_handlers_init:
    logger.info("Using new handler architecture")
    try:
        _prune_legacy_handlers_for_new_mode()
        from handlers import BasicHandler, SubscriptionHandler, AnalyticsHandler, CallbackHandler
        basic_handler = BasicHandler()
        basic_handler.register(dp)
        logger.info("New basic handlers registered")

        subscription_handler = SubscriptionHandler()
        subscription_handler.register(dp)
        logger.info("New subscription handlers registered")

        analytics_handler = AnalyticsHandler()
        analytics_handler.register(dp)
        logger.info("New analytics handlers registered")

        callback_handler = CallbackHandler()
        callback_handler.register(dp)
        logger.info("New callback handlers registered")
    except Exception as e:
        logger.error(f"Failed to register new handlers: {e}", exc_info=True)
        logger.info("Falling back to legacy handlers")
        use_new_handlers_init = False

if not use_new_handlers_init:
    logger.info("Using legacy handler architecture")
    from aiogram import F
    
                           
    dp.message.register(cmd_start_old, Command("start"))
    dp.message.register(cmd_help_old, Command("help"))
    dp.message.register(cmd_mysubs_cmd_old, Command("mysubs"))
    dp.message.register(cmd_unsubscribe_old, Command("unsubscribe"))
    dp.message.register(cmd_stats_old, Command("stats"))
    dp.message.register(cmd_all_list_old, Command("all_list"))
    dp.message.register(cmd_top_drops_old, Command("top_drops"))
    dp.message.register(
        handle_url_old,
        F.text.contains("trendyol.com") | F.text.contains("ty.gl/")
    )
    
                                                   
    dp.callback_query.register(callback_handler_old)
    logger.info("Legacy callback handlers registered")

                         
dp.message.register(cmd_admin, Command("admin"))
dp.message.register(cmd_health, Command("health"))
logger.info("Admin commands registered")

          
async def set_commands_menu():
    """Устанавливает меню команд для бота в Telegram"""
    from aiogram.types import BotCommand

    commands = [
        BotCommand(command="start", description="🚀 Start the bot"),
        BotCommand(command="help", description="❓ Help and commands"),
        BotCommand(command="mysubs", description="📃 My subscriptions"),
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
        await bot.set_my_commands(commands)
        logger.info("✅ Bot commands menu has been set successfully")
    except Exception as e:
        logger.error(f"❌ Failed to set bot commands menu: {e}")


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
        await bot.session.close()
        logger.info("Bot HTTP session closed")
    except Exception:
        logger.exception("Failed to close bot HTTP session")


async def main():
                               
    await set_commands_menu()

                                      
    dp.message.middleware(AntiSpamMiddleware())
    dp.callback_query.middleware(AntiSpamMiddleware())
                                                                            
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Webhook deleted / cleared (if existed)")
    except Exception as e:
        logger.warning("Failed to delete webhook (may be fine): %s", e)

                                                     
    await start_scheduler_async(delay=0.0)

    logger.info("Bot polling started")
    try:
        await dp.start_polling(bot)
    finally:
        await shutdown_runtime()

async def check_blocked_users():
    """Проверить, кто заблокировал бота"""
    try:
        from database import get_connection
        from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest

        admin_user_ids = ADMIN_IDS                                                

        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT user_id FROM users")
            user_ids = [row[0] for row in cursor.fetchall()]

        blocked_users = []
        active_users = []

        for user_id in user_ids:
            try:
                                                           
                await bot.send_chat_action(chat_id=user_id, action="typing")
                active_users.append(user_id)
                await asyncio.sleep(0.1)                                                
            except TelegramForbiddenError:
                                                
                blocked_users.append(user_id)
            except TelegramBadRequest as e:
                if "chat not found" in str(e).lower() or "user not found" in str(e).lower():
                    blocked_users.append(user_id)
            except Exception as e:
                logger.warning(f"Error checking user {user_id}: {e}")
                                                                      
                active_users.append(user_id)

        return blocked_users, active_users

    except Exception as e:
        logger.exception(f"Error in check_blocked_users: {e}")
        return [], []

async def admin_check_blocked(message: types.Message):
    """Показать список заблокировавших бота пользователей"""
    user_id = _get_request_user_id(message)
    if not is_admin(user_id):
        await message.answer(t(user_id, "admin_access_denied"))
        return

    await message.answer("🔍 Проверяю заблокированных пользователей...")

    blocked_users, active_users = await check_blocked_users()

    response = "🚫 <b>Проверка блокировки бота</b>\n\n"

    if blocked_users:
        response += f"❌ <b>Заблокировали бота ({len(blocked_users)}):</b>\n"
        for uid in blocked_users[:20]:                          
            response += f"• <code>{uid}</code>\n"
        if len(blocked_users) > 20:
            response += f"... и еще {len(blocked_users) - 20} пользователей\n"
        response += "\n"
    else:
        response += "✅ <b>Никто не заблокировал бота!</b>\n\n"

    response += f"✅ <b>Активных пользователей:</b> {len(active_users)}\n"
    response += f"📊 <b>Всего проверено:</b> {len(blocked_users) + len(active_users)}"

                                                    
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Список пользователей", callback_data="admin_users_refresh")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats_refresh")]
    ])

    await message.answer(response, reply_markup=keyboard, parse_mode="HTML")

if __name__ == "__main__":
    asyncio.run(main())
