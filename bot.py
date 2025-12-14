import asyncio
import json
import logging
import sqlite3
from typing import Optional, List, Tuple, Dict, Any
from datetime import datetime, timedelta
import io
import re
import os
import csv
import time
import aiohttp
import shutil
from pathlib import Path

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton, CallbackQuery
)

from config import BOT_TOKEN, _check_bot_token, USE_NEW_HANDLERS
import aiogram
from database import (
    init_db,
    add_user_if_not_exists,
    add_subscription,
    get_user_subscriptions,
    remove_subscription,
    get_all_subscriptions,
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
    save_price_points_batch
)
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

# matplotlib is imported lazily in the history handler to avoid hard dependency

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Проверяем что BOT_TOKEN установлен перед созданием Bot
_check_bot_token()

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# CHANGED: default notify mode (можно поменять на "discount" если хочешь)
try:
    from config import DEFAULT_NOTIFY_MODE  # optional config override
except Exception:
    DEFAULT_NOTIFY_MODE = "hourly"  # CHANGED: default now hourly; change to "discount" if preferred

# locales loader
def load_locale(lang_code: str) -> dict:
    try:
        with open(f"locales/{lang_code}.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("Locale load failed for %s: %s", lang_code, e)
        return {}

LOCALES = {
    "ru": load_locale("ru"),
    "en": load_locale("en"),
    "az": load_locale("az"),
    "tr": load_locale("tr")
}

# Admin configuration
ADMIN_IDS = [975282591]  # Add your Telegram user ID here
DB = "trendyol_bot.db"

# Health check variables
last_health_check = 0
health_check_interval = 60  # seconds

# User state for alert editing
alert_edit_state = {}  # user_id -> sub_id
report_state = {}  # user_id -> report_data

def t(user_id: int, key: str) -> str:
    """Return localized string for user; fallback to ru or key."""
    try:
        lang = get_user_language(user_id) or "ru"
    except Exception:
        lang = "ru"
    loc = LOCALES.get(lang, LOCALES.get("ru", {}))
    return loc.get(key, key)

init_db()

# --- helpers
def get_next_notification_time(mode: str, last_notify_time: Optional[int], notify_interval: Optional[int], user_id: int) -> str:
    """
    Рассчитывает время следующего уведомления для подписки.
    Возвращает строку с описанием времени или типа уведомлений.
    """
    try:
        if mode == "discount":
            # Для режима "только при скидке" показываем, что уведомления приходят при изменениях
            return t(user_id, "next_notify_discount")
        elif mode == "hourly":
            # Для почасового режима рассчитываем точное время следующего уведомления
            if last_notify_time and notify_interval:
                # notify_interval в минутах, переводим в секунды
                interval_seconds = notify_interval * 60
                next_time = last_notify_time + interval_seconds
                current_time = int(time.time())

                if next_time > current_time:
                    # Показываем время в формате HH:MM
                    dt = datetime.fromtimestamp(next_time)
                    return dt.strftime("%H:%M")
                else:
                    # Если время уже прошло, показываем ближайшее следующее время
                    # Округляем до следующего часа
                    current_hour = datetime.now().hour
                    next_hour = (current_hour + 1) % 24
                    return f"{next_hour:02d}:00"
            else:
                # Если нет данных, показываем следующий час
                next_hour = (datetime.now().hour + 1) % 24
                return f"{next_hour:02d}:00"
        else:
            return t(user_id, "next_notify_unknown")

    except Exception as e:
        logger.debug(f"Error calculating next notification time: {e}")
        return t(user_id, "next_notify_unknown")
def convert_to_turkish_url(url: str) -> str:
    """Convert English Trendyol URL to Turkish version for better parsing"""
    if "/en/" in url:
        # Remove the /en/ part to get Turkish version
        turkish_url = url.replace("/en/", "/")
        logger.info(f"Converted English URL to Turkish: {url} -> {turkish_url}")
        return turkish_url
    return url

async def resolve_short_url(url: str) -> str:
    """Resolve Trendyol short URLs (ty.gl) and convert to Turkish version"""
    original_url = url
    if "ty.gl/" in url:
        try:
            # Simple redirect resolution for ty.gl links
            # ty.gl redirects to trendyol.com, we can extract the path
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(url, allow_redirects=True, timeout=10) as response:
                    final_url = str(response.url)
                    if "trendyol.com" in final_url:
                        url = final_url
        except Exception as e:
            logger.warning(f"Failed to resolve short URL {original_url}: {e}")

    # Convert English URLs to Turkish for better parsing
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
    if not u:
        return False
    try:
        ul = (u or "").lower()
        return ("trendyol.com" in ul) and ("/p/" in ul or "-p-" in ul)
    except (AttributeError, TypeError):
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
    
    # Список форматов для попытки парсинга (в порядке вероятности)
    formats = [
        "%d.%m.%Y %H:%M:%S",      # 20.09.2025 14:30:00
        "%d.%m.%Y %H:%M",         # 20.09.2025 14:30
        "%d.%m.%Y",                # 20.09.2025
        "%Y-%m-%d %H:%M:%S",       # 2025-09-20 14:30:00
        "%Y-%m-%d %H:%M",          # 2025-09-20 14:30
        "%Y-%m-%d",                # 2025-09-20
        "%d/%m/%Y",                # 20/09/2025
        "%m/%d/%Y",                # 09/20/2025
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
            # if already ISO-like
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
    timeout_seconds: float = 10.0
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
        if image:
            try:
                await asyncio.wait_for(
                    bot.send_photo(user_id, photo=image, caption=text),
                    timeout=timeout_seconds
                )
                logger.debug(f"Photo notification sent to {user_id}")
                return True
            except asyncio.TimeoutError:
                logger.warning(f"Photo send timeout for user {user_id}, falling back to text")
                # Fallback на текст если фото долго грузится
                try:
                    await asyncio.wait_for(
                        bot.send_message(user_id, text),
                        timeout=timeout_seconds
                    )
                    return True
                except Exception as e:
                    logger.exception(f"Fallback text message failed for {user_id}: {e}")
                    return False
        else:
            await asyncio.wait_for(
                bot.send_message(user_id, text),
                timeout=timeout_seconds
            )
            logger.debug(f"Text notification sent to {user_id}")
            return True
            
    except asyncio.TimeoutError:
        logger.error(f"Notification timeout for user {user_id}")
        return False
    except aiogram.exceptions.TelegramForbiddenError:
        logger.warning(f"User {user_id} blocked the bot")
        return False
    except aiogram.exceptions.TelegramBadRequest as e:
        logger.warning(f"Bad request for user {user_id}: {e}")
        return False
    except Exception as e:
        logger.exception(f"Unexpected error sending notification to {user_id}: {e}")
        return False

async def send_history_plot(user_id: int, url: str, hist):
    # hist: List[Tuple[str|datetime, float]]
    processed = []
    for d, p in hist:
        parsed_dt = None
        if isinstance(d, str):
            # Используем улучшенный парсер с поддержкой разных форматов
            parsed_dt = parse_date_flexible(d)
        elif isinstance(d, datetime):
            parsed_dt = d

        if parsed_dt:
            processed.append((parsed_dt, float(p)))
        else:
            # Дату не распознали, используем как есть
            logger.debug(f"Could not parse date for history: {d}")
            processed.append((d, float(p)))

    # Сортировка, если даты удалось распознать
    if processed and isinstance(processed[0][0], datetime):
        processed.sort(key=lambda x: x[0])
        x_vals = [x[0] for x in processed]
    else:
        x_vals = list(range(len(processed)))
    y_vals = [x[1] for x in processed]

    try:
        # Попытка использовать matplotlib
        import matplotlib
        matplotlib.use('Agg')  # Важно установить до импорта pyplot
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates

        # Отрисовка графика
        plt.style.use('seaborn-v0_8-darkgrid')
        fig, ax = plt.subplots(figsize=(10, 5))

        ax.plot(x_vals, y_vals, marker='o', linestyle='-', color='dodgerblue')

        if processed and isinstance(processed[0][0], datetime):
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%d.%m'))
            fig.autofmt_xdate()

        ax.fill_between(x_vals, y_vals, alpha=0.1, color='dodgerblue')

        ax.set_title(t(user_id, "history_chart_title"), fontsize=14, weight='bold')
        ax.set_xlabel(t(user_id, "history_chart_x"), fontsize=10)
        ax.set_ylabel(t(user_id, "history_chart_y"), fontsize=10)
        ax.grid(True, which='both', linestyle='--', linewidth=0.5)

        # Добавляем аннотации к мин и макс
        if y_vals:
            min_price = min(y_vals)
            max_price = max(y_vals)
            min_idx = y_vals.index(min_price)
            max_idx = y_vals.index(max_price)
            ax.annotate(f"Min: {min_price}", xy=(x_vals[min_idx], min_price), xytext=(-20, -30),
                        textcoords='offset points', arrowprops=dict(arrowstyle="->", connectionstyle="arc3,rad=-0.2"))
            ax.annotate(f"Max: {max_price}", xy=(x_vals[max_idx], max_price), xytext=(20, 20),
                        textcoords='offset points', arrowprops=dict(arrowstyle="->", connectionstyle="arc3,rad=0.2"))

        buf = io.BytesIO()
        plt.tight_layout()
        plt.savefig(buf, format='png', dpi=100)
        plt.close(fig)
        buf.seek(0)

        # Проверяем размер файла (Telegram limit: 10MB)
        if buf.tell() > 10 * 1024 * 1024:  # 10MB
            logger.warning("Plot too large (%d bytes), reducing quality", buf.tell())
            buf.seek(0)
            buf.truncate(0)
            plt.savefig(buf, format='png', dpi=50)  # Lower quality
            buf.seek(0)

        caption_text = t(user_id, "history_caption").format(url=url)

        await bot.send_photo(user_id, buf, caption=caption_text)
        buf.close()

    except ImportError:
        logger.warning("matplotlib not available, falling back to text output")
        # Фолбэк на текстовую историю с ASCII графикой
        if not processed:
            await bot.send_message(user_id, t(user_id, "history_not_found"))
            return

        min_price = min(p for _, p in processed)
        max_price = max(p for _, p in processed)
        price_range = max_price - min_price

        GRAPH_CHARS = "▁▂▃▄▅▆▇█"
        lines_out = [t(user_id, "history_caption").format(url=url), "", f"Max: {max_price:.2f} TL", f"Min: {min_price:.2f} TL", ""]

        for date, price in processed:
            if price_range == 0:
                normalized = len(GRAPH_CHARS) - 1
            else:
                normalized = int((price - min_price) / price_range * (len(GRAPH_CHARS) - 1))
            graph_char = GRAPH_CHARS[normalized]
            date_str = date.strftime('%d.%m.%Y') if isinstance(date, datetime) else str(date)
            lines_out.append(f"{date_str}: {price:.2f} TL {graph_char}")

        await bot.send_message(user_id, "\n".join(lines_out))


async def send_history_for_subscription(user_id: int, sub_id: int, url: str):
    """Helper that prefers local DB history and falls back to akakce scraper."""
    # Сначала пробуем локальную БД
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

# --- Trending helpers and state
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
# ---------------- UI builders (localized) ----------------
def get_main_kb(user_id: int) -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=t(user_id, "btn_subscribe")), KeyboardButton(text=t(user_id, "btn_subs"))],
            [KeyboardButton(text=t(user_id, "btn_recommend")), KeyboardButton(text=t(user_id, "btn_trending"))],
            [KeyboardButton(text=t(user_id, "btn_language")), KeyboardButton(text=t(user_id, "btn_unsubscribe"))]
        ],
        resize_keyboard=True
    )
    return kb

def get_notify_inline_kb(user_id: int, sub_id: Optional[int] = None) -> InlineKeyboardMarkup:
    # If sub_id provided, include it in callback_data; otherwise fallback to simple callbacks (handled elsewhere)
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
            # sub is canonical: id, user_id, url, notify_mode, last_price, product_title, product_image, ...
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

# start
# OLD HANDLER: moved to handlers/basic.py
async def cmd_start_old(message: types.Message):
    add_user_if_not_exists(message.from_user.id)
    await message.answer(t(message.from_user.id, "start_text"), reply_markup=get_main_kb(message.from_user.id))

@dp.message(lambda m: m.text == t(m.from_user.id, "btn_language"))
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

@dp.message(Command("language"))
async def cmd_language_command(message: types.Message):
    parts = (message.text or "").split()
    if len(parts) > 1:
        code = parts[1].lower()
        if code in {"ru", "en", "az", "tr"}:
            set_user_language(message.from_user.id, code)
            try:
                await message.answer(t(message.from_user.id, "lang_changed"))
            except:
                pass
            try:
                await bot.send_message(message.from_user.id, t(message.from_user.id, "start_text"), reply_markup=get_main_kb(message.from_user.id))
            except:
                pass
        else:
            await message.answer(t(message.from_user.id, "invalid_language"))
    else:
        await cmd_lang_message(message)

# --- Commands: help, mysubs alias, history, unsubscribe, setmode, about, ping, settings
# OLD HANDLER: moved to handlers/basic.py
async def cmd_help_old(message: types.Message):
    await message.answer(t(message.from_user.id, "help_text"))

@dp.message(Command("report"))
async def cmd_report(message: types.Message):
    """Handle user reports/support requests"""
    user_id = message.from_user.id
    parts = (message.text or "").split(maxsplit=1)

    if len(parts) < 2:
        # Ask user to provide report text
        report_state[user_id] = {"step": "waiting_text"}
        await message.answer(t(user_id, "report_prompt"))
        return

    # Direct report text provided
    report_text = parts[1].strip()
    if len(report_text) < 5:
        await message.answer(t(user_id, "report_too_short"))
        return

    await submit_user_report(user_id, report_text, message)

# OLD HANDLER: moved to handlers/subscription_handler.py
async def cmd_mysubs_cmd_old(message: types.Message):
    await cmd_mysubs(message)

@dp.message(Command("history"))
async def cmd_history(message: types.Message):
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(t(message.from_user.id, "cmd_history_usage"))
        return
    arg = parts[1].strip()

    # Try treat as subscription id
    if arg.isdigit():
        sid = int(arg)
        sub = get_subscription(sid)
        if not sub or sub[1] != message.from_user.id:
            await message.answer(t(message.from_user.id, "no_subs"))
            return
        # Безопасная распаковка: get_subscription возвращает 13 полей (с price_alert)
        if len(sub) >= 13:
            url = sub[2]
        elif len(sub) >= 12:
            url = sub[2]
        else:
            url = sub[2] if len(sub) > 2 else ""
        await message.answer(t(message.from_user.id, "history_fetching"))
        # First try local DB history
        db_hist = get_price_history(sid, limit=1000)
        if db_hist and len(db_hist) >= 2:
            # convert (ts, price) -> [(iso_date, price), ...] using safe conversion
            hist = [(safe_ts_to_iso(r[0]), r[1]) for r in db_hist]
            await send_history_plot(message.from_user.id, url, hist)
            return

        # Fallback to Akakce-based history
        hist = await get_price_history_from_akakce_async(url)
        if not hist:
            await message.answer(t(message.from_user.id, "history_not_found"))
            return
        # Save a few recent points to DB for faster future responses (non-blocking)
        try:
            for d_str, p in hist[-30:]:
                try:
                    # attempt to parse date to ts
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

    # Otherwise treat as URL
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

# OLD HANDLER: moved to handlers/subscription_handler.py
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
        # безопасная проверка владельца
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
    
    # Безопасная проверка владельца
    if len(sub) >= 2 and sub[1] != user_id:
        await message.answer(t(user_id, "price_alert_not_your_sub"))
        return
    
    try:
        update_subscription_settings(sid, price_alert=target_price)
        current_price = sub[4] if len(sub) > 4 else None
        
        if current_price and current_price <= target_price:
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
    except Exception as e:
        logger.exception("Error setting price_alert: %s", e)
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
        parts = message.text.split()
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
                
                # Минимальная цена
                if "min:" in message.text:
                    try:
                        min_price = float(message.text.split("min:")[1].split()[0])
                        update_args["min_price"] = min_price
                    except:
                        pass
                        
                # Максимальная цена
                if "max:" in message.text:
                    try:
                        max_price = float(message.text.split("max:")[1].split()[0])
                        update_args["max_price"] = max_price
                    except:
                        pass
                        
                # Процент изменения
                if "percent:" in message.text:
                    try:
                        notify_percent = float(message.text.split("percent:")[1].split()[0])
                        update_args["notify_percent"] = notify_percent
                    except:
                        pass
                
                if update_args:
                    update_subscription_settings(sub_id, **update_args)
                    await message.answer(t(message.from_user.id, "price_alerts_updated"))
                    return
                    
            await message.answer(t(message.from_user.id, "price_alerts_usage"))
            
        elif subcmd == "interval":
            if len(parts) == 4 and parts[2].isdigit() and parts[3].isdigit():
                sub_id = int(parts[2])
                minutes = int(parts[3])
                
                if minutes < 15:  # минимальный интервал 15 минут
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

# ADDED: manual runcheck for testing
@dp.message(Command("runcheck"))
async def cmd_runcheck(message: types.Message):
    """Run check_all manually (for testing). Anyone can call it; adjust for admin-only if needed."""
    await message.answer(t(message.from_user.id, "please_wait"))
    try:
        await check_all()
        await message.answer("✅ " + t(message.from_user.id, "done"))
    except Exception as e:
        logger.exception("manual runcheck error: %s", e)
        await message.answer(t(message.from_user.id, "error_runcheck") + f": {e}")

# === ВОЛНА 2: НОВЫЕ КОМАНДЫ ===

# /stats <ID> - Статистика цен по подписке
# OLD HANDLER: moved to handlers/analytics_handler.py
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
        
        # Проверяем владельца
        if sub[1] != message.from_user.id:
            await message.answer(t(message.from_user.id, "error_not_your_sub"))
            return
        
        stats = get_price_stats(sub_id)
        
        if stats['count'] == 0:
            await message.answer(t(message.from_user.id, "stats_no_history"))
            return
        
        # Форматируем статистику
        curr = f"{stats['current']:.2f}" if stats['current'] else "—"
        min_p = f"{stats['min']:.2f}" if stats['min'] else "—"
        max_p = f"{stats['max']:.2f}" if stats['max'] else "—"
        avg_p = f"{stats['avg']:.2f}" if stats['avg'] else "—"
        
        # Используем локализованный заголовок
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

# /all_list - Компактный список всех подписок
# OLD HANDLER: moved to handlers/analytics_handler.py
async def cmd_all_list_old(message: types.Message):
    """Show all subscriptions in compact table format"""
    try:
        subs = get_user_subscriptions(message.from_user.id)
        
        if not subs:
            await message.answer(t(message.from_user.id, "no_subs"))
            return
        
        # Форматируем в таблицу
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

# /top_drops - Топ товаров с падением цены
# OLD HANDLER: moved to handlers/analytics_handler.py
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


# /export [csv|json] - Export user's subscriptions to CSV or JSON and save backup
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
            # send to user
            with open(fname, "rb") as f:
                await bot.send_document(user_id, types.InputFile(f, filename=os.path.basename(fname)))
            await message.answer(t(user_id, "export_done").format(path=fname))
            return

        # csv
        fname = f"backups/subscriptions_{user_id}_{ts}.csv"
        # determine columns (stable order)
        cols = [
            'id','user_id','url','mode','last_price','product_title','product_image',
            'min_price','max_price','notify_percent','notify_interval','last_notify_time','price_alert','tags'
        ]
        # write CSV with BOM for Excel compatibility
        with open(fname, "w", encoding="utf-8-sig", newline='') as f:
            writer = csv.DictWriter(f, fieldnames=cols)
            writer.writeheader()
            for row in subs:
                # ensure all keys present
                safe_row = {k: row.get(k, "") for k in cols}
                writer.writerow(safe_row)

        with open(fname, "rb") as f:
            await bot.send_document(user_id, types.InputFile(f, filename=os.path.basename(fname)))

        await message.answer(t(user_id, "export_done").format(path=fname))

    except Exception as e:
        logger.exception("Export command error: %s", e)
        await message.answer(t(message.from_user.id, "error_generic"))


# /history_export <ID> [csv|json] - экспорт истории цен по подписке
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
        # parse optional args: any numeric => days, csv/json => fmt
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

        # Получаем историю: если days задан — используем локальную резонную выборку по дням,
        # иначе берём полный dump (limit)
        if days is not None:
            rows = get_local_price_history(sub_id, days=min(days, 365))  # Max 1 year
        else:
            rows = get_price_history(sub_id, limit=5000)  # Reduced limit for safety

        if not rows:
            await message.answer(t(message.from_user.id, "history_export_no_data"))
            return

        os.makedirs("backups", exist_ok=True)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')

        # JSON payload: adapt depending on row type (ts int or iso string)
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

        # CSV
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


# /history_plot <ID> [days] - build and send PNG price history plot
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

        # get history (prefer local summary for days)
        if days is not None:
            rows = get_local_price_history(sub_id, days=min(days, 180))  # Max 6 months for plots
        else:
            rows = get_price_history(sub_id, limit=2000)  # Reduced limit for plots

        if not rows:
            await message.answer(t(message.from_user.id, "history_plot_no_data"))
            return

        # normalize to list of (iso, price) for send_history_plot
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


# /compare <ID> - сравнение цен на похожие товары
@dp.message(Command("compare"))
async def cmd_compare(message: types.Message):
    """Compare prices of similar products"""
    try:
        from scraper import get_similar_products_comparison

        args = message.text.split()
        if len(args) < 2 or not args[1].isdigit():
            await message.answer(t(message.from_user.id, "cmd_compare_usage"))
            return

        sub_id = int(args[1])
        sub = get_subscription(sub_id)

        if not sub:
            await message.answer(t(message.from_user.id, "no_subs_found_id"))
            return

        # Проверяем владельца
        if sub[1] != message.from_user.id:
            await message.answer(t(message.from_user.id, "error_not_your_sub"))
            return

        # Отправляем сообщение о загрузке
        await message.answer(t(message.from_user.id, "compare_loading"))

        # Получаем сравнение
        comparison = await get_similar_products_comparison(message.from_user.id, sub_id)

        if comparison:
            await message.answer(comparison, parse_mode="Markdown")
        else:
            await message.answer(t(message.from_user.id, "compare_no_similar"))

    except Exception as e:
        logger.exception("compare command error: %s", e)
        await message.answer(t(message.from_user.id, "error_generic"))


# --- callback handler (languages, modes, unsubscribe, history)
# OLD HANDLER: moved to handlers/callback_handler.py
async def callback_handler_old(cq: CallbackQuery):
    data = cq.data or ""
    user_id = cq.from_user.id

    try:
        # --- Смена языка ---
        if data.startswith("lang:"):
            await cq.answer()
            lang = data.split(":", 1)[1]
            set_user_language(user_id, lang)
            try:
                await bot.send_message(user_id, t(user_id, "start_text"), reply_markup=get_main_kb(user_id))
                await cq.message.edit_text(t(user_id, "lang_changed"))
            except aiogram.exceptions.TelegramBadRequest as e:
                logger.warning("Bad request updating language for %s: %s", user_id, e)
            except Exception as e:
                logger.exception("Failed to send updated main kb or edit msg for %s: %s", user_id, e)
            return

        # --- Отписка от одного товара ---
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

        # --- Подтверждение массовой отписки ---
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

        # --- Смена режима уведомлений ---
        if data.startswith("mode:"):
            parts = data.split(":")
            if len(parts) == 3:
                _, sub_id_str, mode = parts
                try:
                    sub_id = int(sub_id_str)
                    sub = get_subscription(sub_id)
                    logger.debug("mode callback: sub=%r user=%s", sub, user_id)
                    # Проверяем владельца в безопасном режиме
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

                    # Обновляем интерфейс и подтверждаем пользователю
                    try:
                        await cq.message.edit_reply_markup(reply_markup=subscription_controls_kb_for_user(user_id, sub_id))
                        await cq.answer(t(user_id, "mode_changed_short").format(mode=mode))
                    except Exception as e:
                        logger.exception("mode callback UI update failed for sub %s: %s", sub_id, e)
                        # Всё ещё возвращаем успех пользователю, т.к. БД уже обновлена
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

        # --- Редактирование подписки ---
        if data.startswith("edit_sub:"):
            await cq.answer()
            try:
                sub_id = int(data.split(":", 1)[1])
                sub = get_subscription(sub_id)
                if not sub or sub[1] != user_id:
                    await cq.answer(t(user_id, "error_not_your_sub"), show_alert=True)
                    return
                
                # Формируем детальную информацию о подписке
                try:
                    (_, _, url, mode, last_price, product_title, product_image,
                     min_price, max_price, notify_percent, notify_interval, last_notify_time, price_alert) = sub
                except ValueError:
                    (_, _, url, mode, last_price, product_title, product_image,
                     min_price, max_price, notify_percent, notify_interval, last_notify_time) = sub[:12]
                    price_alert = None
                
                # Формируем текст с информацией о подписке
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
                
                # Отправляем сообщение с меню редактирования
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

        # --- Редактирование ценового алерта ---
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
                alert_edit_state[user_id] = sub_id  # Устанавливаем состояние для ввода цены
                await cq.answer()

            except ValueError:
                await cq.answer(t(user_id, "error_invalid_id"), show_alert=True)
            except Exception as e:
                logger.exception("alert_edit callback error: %s", e)
                await cq.answer(t(user_id, "error_generic"), show_alert=True)
            return

        # --- Удаление алерта ---
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

        # --- Возврат к списку алертов ---
        if data == "alerts_back":
            await cq.answer()
            # Повторно вызываем команду alerts
            await cmd_alerts(cq.message)
            return

        # --- Запрос истории цен ---
        if data.startswith("history:"):
            await cq.answer(t(user_id, "history_fetching_short"))
            try:
                sid = int(data.split(":", 1)[1])
                sub = get_subscription(sid)
                if not sub or sub[1] != user_id:
                    await bot.send_message(user_id, t(user_id, "error_not_your_sub"))
                    return
                url = sub[2]
                # Prefer DB history
                db_hist = get_price_history(sid, limit=1000)
                if db_hist and len(db_hist) >= 2:
                    hist = [(safe_ts_to_iso(r[0]), r[1]) for r in db_hist]
                    await send_history_plot(user_id, url, hist)
                    return

                hist = await get_price_history_from_akakce_async(url)
                if not hist:
                    await bot.send_message(user_id, t(user_id, "history_not_found"))
                    return
                # Save recent points
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

        # --- Сравнение цен ---
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

        # --- Меню трендов ---
        if data == "trend:all":
            await cq.answer()
            await bot.send_message(user_id, t(user_id, "please_wait"))
            try:
                items = await get_trending_all_top3_async()
                await send_trending_list(user_id, items)
                await cq.message.delete() # Удаляем исходное меню
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

        # --- Admin user details ---
        if data.startswith("user_details:"):
            if user_id not in ADMIN_IDS:
                await cq.answer(t(user_id, "admin_only"), show_alert=True)
                return

            try:
                target_user_id = int(data.split(":", 1)[1])
                await cq.answer(t(user_id, "loading"))

                # Get detailed user info
                await admin_user_details_callback(cq.message, target_user_id, user_id)
            except ValueError:
                await cq.answer(t(user_id, "error_invalid_id"), show_alert=True)
            except Exception as e:
                logger.exception("user_details callback error: %s", e)
                await cq.answer(t(user_id, "error_generic"), show_alert=True)
            return

        # --- Admin users refresh ---
        if data == "admin_users_refresh":
            if user_id not in ADMIN_IDS:
                await cq.answer(t(user_id, "admin_only"), show_alert=True)
                return

            await cq.answer(t(user_id, "loading"))
            try:
                # Re-run admin users list
                await admin_users_list_interactive(cq.message)
            except Exception as e:
                logger.exception("admin_users_refresh callback error: %s", e)
                await cq.answer(t(user_id, "error_generic"), show_alert=True)
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

# --- Admin user management callbacks
# OLD HANDLER: moved to handlers/callback_handler.py
async def admin_user_details_callback_old(cq: CallbackQuery):
    """Handle user details button clicks in admin panel"""
    try:
        # Check admin permissions
        if cq.from_user.id not in ADMIN_IDS:
            await cq.answer(t(cq.from_user.id, "admin_only"), show_alert=True)
            return

        # Extract user ID from callback data
        target_user_id = int(cq.data.split(":", 1)[1])

        await cq.answer(t(cq.from_user.id, "loading_user_details"))

        # Get detailed user information
        await admin_user_details_callback(cq.message, target_user_id, cq.from_user.id)

    except ValueError:
        await cq.answer(t(cq.from_user.id, "invalid_user_id"), show_alert=True)
    except Exception as e:
        logger.exception("Error in admin_user_details_callback: %s", e)
        await cq.answer(t(cq.from_user.id, "error_generic"), show_alert=True)

# --- Subscribe flow
@dp.message(lambda m: m.text and (
    t(m.from_user.id, "btn_subscribe") == m.text
    or (
        ("подпис" in m.text.lower())
        and ("мои" not in m.text.lower())
        and ("мои подпис" not in m.text.lower())
        and (m.text != t(m.from_user.id, "btn_subs"))
    )
))
async def cmd_subscribe_ui(message: types.Message):
    await message.answer(t(message.from_user.id, "send_link_prompt"))

# OLD HANDLER: moved to handlers/subscription_handler.py
async def handle_url_old(message: types.Message):
    try:
        raw = (message.text or "").strip()
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

        # Duplicate check by normalized URL
        subs = get_user_subscriptions(message.from_user.id)
        for sub in subs:
            try:
                (sid, user_id, u, mode, last_price, product_title, product_image,
                 min_price, max_price, notify_percent, notify_interval, last_notify_time, price_alert) = sub
            except ValueError:
                # Fallback для старых подписок
                (sid, user_id, u, mode, last_price, product_title, product_image,
                 min_price, max_price, notify_percent, notify_interval, last_notify_time) = sub[:12]
            if normalize_url(u).lower() == url_lower:
                await message.answer(t(message.from_user.id, "already_subscribed"))
                return

        # CHANGED: use DEFAULT_NOTIFY_MODE instead of hardcoded "discount"
        sub_id = add_subscription(message.from_user.id, url, DEFAULT_NOTIFY_MODE)
        # Получаем цену, название и обложку в одном запросе
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

        # Сохраняем title/image в кэше подписки, если они получены
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
                # Формируем сообщение с картинкой, если есть
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
        logger.exception("Error in handle_url for user %s: %s", message.from_user.id, e)
        await message.answer(t(message.from_user.id, "error_generic"))

# Legacy alias for compatibility with older tests and code that expects `handle_url`
handle_url = handle_url_old

# --- Handle alert price input
@dp.message(lambda m: m.from_user and m.from_user.id in alert_edit_state and m.text and not m.text.startswith("/"))
async def handle_alert_price(message: types.Message):
    """Handle user input for setting alert price"""
    user_id = message.from_user.id
    sub_id = alert_edit_state.get(user_id)

    if not sub_id:
        return

    try:
        # Парсим цену
        price_text = message.text.strip().replace(' ', '').replace('TL', '').replace('₺', '')
        target_price = float(price_text)

        if target_price <= 0:
            await message.answer(t(user_id, "price_alert_price_negative"))
            return

        # Проверяем что подписка принадлежит пользователю
        sub = get_subscription(sub_id)
        if not sub or sub[1] != user_id:
            await message.answer(t(user_id, "error_not_your_sub"))
            del alert_edit_state[user_id]
            return

        # Устанавливаем алерт
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

# --- Handle report text input
@dp.message(lambda m: m.from_user and m.from_user.id in report_state and m.text and not m.text.startswith("/"))
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

# --- List subs
@dp.message(lambda m: m.text and (t(m.from_user.id, "btn_subs") == m.text or "мои подпис" in m.text.lower()))
async def cmd_mysubs(message: types.Message):
    user_id = message.from_user.id
    subs = get_user_subscriptions(user_id)
    if not subs:
        await message.answer(t(user_id, "no_subs"))
        return
    
    # Формируем одно сообщение со списком всех подписок
    lines = [t(user_id, "mysubs_header")]
    inline_buttons = []
    
    for sub in subs:
        try:
            (sub_id, _, url, mode, last_price, product_title, product_image,
             min_price, max_price, notify_percent, notify_interval, last_notify_time, price_alert) = sub
        except ValueError:
            # Fallback для старых подписок
            (sub_id, _, url, mode, last_price, product_title, product_image,
             min_price, max_price, notify_percent, notify_interval, last_notify_time) = sub[:12]
            price_alert = None
        
        # Определяем статус подписки
        status_icon = "✅" if last_price is not None else "⚠️"
        status_text = t(user_id, "status_active") if last_price is not None else t(user_id, "status_inactive")
        
        # Форматируем цену
        price_text = f"{last_price:.0f} TL" if last_price is not None else t(user_id, "unknown_price")
        
        # Форматируем режим и время следующего уведомления
        mode_text = t(user_id, "mode_hourly") if mode == "hourly" else t(user_id, "mode_discount")
        next_notify = get_next_notification_time(mode, last_notify_time, notify_interval, user_id)

        # Используем название товара или URL
        title = product_title if product_title else url[:50] + "..." if len(url) > 50 else url

        # Формируем строку для подписки
        sub_line = f"\n{status_icon} *{status_text}* | ID: `{sub_id}`\n"
        sub_line += f"📦 {title}\n"
        sub_line += f"💰 {price_text} | 🔔 {next_notify}\n"
        
        # Добавляем информацию о целевой цене, если установлена
        if price_alert is not None:
            sub_line += f"🎯 {t(user_id, 'price_alert_label')}: {price_alert:.0f} TL\n"
        
        lines.append(sub_line)
        
        # Добавляем кнопку для редактирования этой подписки
        inline_buttons.append([
            InlineKeyboardButton(
                text=f"⚙️ {t(user_id, 'btn_edit')} ID {sub_id}",
                callback_data=f"edit_sub:{sub_id}"
            )
        ])
    
    # Объединяем все строки
    full_text = "\n".join(lines)

    # Проверяем длину сообщения (Telegram limit: 4096 chars)
    if len(full_text) > 4000:
        # Если сообщение слишком длинное, разбиваем на части
        warning_msg = f"⚠️ У вас {len(subs)} подписок. Показываю первые 10:\n\n"
        short_lines = lines[:11]  # header + 10 subs
        short_text = "\n".join(short_lines)
        short_keyboard = InlineKeyboardMarkup(inline_keyboard=inline_buttons[:10])

        await message.answer(warning_msg + short_text, reply_markup=short_keyboard, parse_mode="Markdown")
        return

    # Создаем клавиатуру с кнопками
    keyboard = InlineKeyboardMarkup(inline_keyboard=inline_buttons)

    try:
        await message.answer(full_text, reply_markup=keyboard, parse_mode="Markdown")
    except Exception as e:
        logger.exception("Error sending mysubs list: %s", e)
        # Fallback без Markdown
        full_text_plain = full_text.replace("*", "").replace("`", "")
        await message.answer(full_text_plain, reply_markup=keyboard)

# --- Trending
@dp.message(lambda m: m.text == t(m.from_user.id, "btn_recommend"))
async def cmd_recommend_button(message: types.Message):
    """Обработчик кнопки рекомендаций в меню"""
    await cmd_recommend(message)

@dp.message(lambda m: m.text and (t(m.from_user.id, "btn_trending") == m.text or "тренд" in m.text.lower() or "трен" in m.text.lower()))
async def cmd_trending(message: types.Message):
    await message.answer(t(message.from_user.id, "trending_header"), reply_markup=trending_menu_kb(message.from_user.id))

# --- Trending search text handler
@dp.message(lambda m: m.text and not m.text.startswith("/") and m.from_user and m.from_user.id in TREND_SEARCH_AWAIT)
async def trending_search_text(message: types.Message):
    user_id = message.from_user.id
    q = (message.text or "").strip()
    if not q:
        await message.answer(t(user_id, "trending_enter_query"))
        return
    # consume state
    if user_id in TREND_SEARCH_AWAIT:
        TREND_SEARCH_AWAIT.remove(user_id)
    try:
        await message.answer(t(user_id, "trending_searching"))
        items = await get_trending_by_search_top3_async(q)
        await send_trending_list(user_id, items)
    except Exception as e:
        logger.exception("trending search error: %s", e)
        await message.answer(t(user_id, "trending_no_results"))
# --- Unsubscribe all
@dp.message(lambda m: m.text and (t(m.from_user.id, "btn_unsubscribe") == m.text or "отпис" in m.text.lower()))
async def cmd_unsubscribe_all(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅", callback_data="confirm_unsub_all:yes"),
        InlineKeyboardButton(text="🚫", callback_data="confirm_unsub_all:no"),
    ]])
    await message.answer(t(message.from_user.id, "btn_unsubscribe") + " ❓", reply_markup=kb)

# --- Scheduler job
scheduler = AsyncIOScheduler()

async def send_grouped_notifications(grouped_notifications: Dict[int, List[Tuple[str, Optional[str]]]]) -> None:
    """
    Отправляет групповые уведомления пользователям.
    grouped_notifications: user_id -> [(notification_text, image_url), ...]
    """
    for user_id, notifications in grouped_notifications.items():
        try:
            if len(notifications) == 1:
                # Одно уведомление - отправляем как обычно
                text, image = notifications[0]
                await send_notification_safe(user_id, text, image)
            else:
                # Несколько уведомлений - группируем в одно сообщение
                grouped_text = f"🔔 <b>ОБНОВЛЕНИЯ ЦЕН</b> ({len(notifications)})\n\n"

                for i, (text, image) in enumerate(notifications[:10], 1):  # Максимум 10 уведомлений
                    # Убираем общие части и оставляем только суть
                    clean_text = text.replace("💰 ", "").replace("📉 ", "").replace("📈 ", "")
                    grouped_text += f"{i}. {clean_text}\n"

                if len(notifications) > 10:
                    grouped_text += f"\n... и ещё {len(notifications) - 10} обновлений"

                # Отправляем групповое уведомление без изображения
                await send_notification_safe(user_id, grouped_text, image=None)

        except Exception as e:
            logger.exception("Error sending grouped notifications to user %s: %s", user_id, e)

async def check_all():
    logger.info("Scheduler job: checking subscriptions")
    subs = get_all_subscriptions()
    total = len(subs)
    logger.info("Found %d subscriptions to check", total)
    
    # ОПТИМИЗАЦИЯ: Кэш для пользовательских настроек (избегаем N+1 запросов)
    user_settings_cache = {}
    
    def get_cached_user_settings(user_id: int):
        """Возвращает настройки пользователя из кэша или БД."""
        if user_id not in user_settings_cache:
            user_settings_cache[user_id] = get_user_settings(user_id)
        return user_settings_cache[user_id]
    
    sem = asyncio.Semaphore(10)
    processed_count = 0
    alerted_count = 0

    # ПАКЕТНАЯ ОБРАБОТКА: собираем все точки цены для сохранения
    price_points_batch = []

    # ГРУППОВЫЕ УВЕДОМЛЕНИЯ: собираем уведомления по пользователям
    grouped_notifications = {}  # user_id -> list of (text, image)

    async def process(sub):
        nonlocal processed_count, alerted_count
        # Обновлена распаковка: теперь включает price_alert
        try:
            (sub_id, user_id, url, mode, last_price, product_title, product_image,
             min_price, max_price, notify_percent, notify_interval, last_notify_time, price_alert) = sub
        except ValueError:
            # Fallback для старых подписок без price_alert
            (sub_id, user_id, url, mode, last_price, product_title, product_image,
             min_price, max_price, notify_percent, notify_interval, last_notify_time) = sub[:12]
            price_alert = None
            
        async with sem:
            try:
                # Проверяем тихие часы пользователя с использованием кэша
                current_hour = datetime.now().hour
                lang, quiet_start, quiet_end = get_cached_user_settings(user_id)
                
                is_quiet_time = False
                if quiet_start <= quiet_end:
                    is_quiet_time = quiet_start <= current_hour < quiet_end
                else:  # например, 23:00 - 7:00
                    is_quiet_time = current_hour >= quiet_start or current_hour < quiet_end
                    
                if is_quiet_time:
                    logger.debug(f"Quiet hours for user {user_id} ({current_hour}:00)")
                    return

                # Проверяем интервал уведомлений
                current_time = int(time.time())
                if last_notify_time and notify_interval:
                    if current_time - last_notify_time < notify_interval * 60:
                        return

                # fetch price and optionally title/image to enrich notifications
                try:
                    price, title, image = await get_product_info_async(url)
                except asyncio.TimeoutError:
                    logger.warning("Timeout fetching product info for sub %s", sub_id)
                    return  # Skip this subscription for now
                except aiohttp.ClientError as e:
                    logger.warning("Network error fetching product info for sub %s: %s", sub_id, e)
                    return  # Skip this subscription for now
                except Exception as e:
                    logger.exception("Unexpected error fetching product info for sub %s: %s", sub_id, e)
                    return  # Skip this subscription for now

                # Prefer cached DB metadata if live fetch didn't return them
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
                        # Store initial price point
                        add_price_point(sub_id, url, float(price), source='collector')
                    except Exception:
                        logger.exception("Failed to add initial price point for sub %s", sub_id)
                    logger.debug("Set initial last_price for sub %s -> %s", sub_id, price)
                    return

                # Проверяем условия для уведомления
                notification_needed = False
                notification_text = None

                # НОВОЕ: Проверка price_alert (целевая цена)
                if price_alert is not None and price <= price_alert:
                    notification_needed = True
                    notification_text = (
                        f"🎯 Цена достигла целевого значения!\n"
                        f"Целевая цена: {price_alert:.0f} TL\n"
                        f"Текущая цена: {price:.0f} TL\n"
                        f"🔗 {url}"
                    )
                    # После достижения целевой цены очищаем её
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
                
                # Проверяем диапазон цен
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
                    # ГРУППОВЫЕ УВЕДОМЛЕНИЯ: добавляем в очередь вместо немедленной отправки
                    if user_id not in grouped_notifications:
                        grouped_notifications[user_id] = []
                    grouped_notifications[user_id].append((notification_text, image))

                    alerted_count += 1
                    update_notify_time(sub_id)

                # Обновляем последнюю цену, если она изменилась
                if price != last_price:
                    # Save price point but avoid duplicates: check last stored point
                    try:
                        last_point = get_last_price_point(sub_id)
                        should_insert = True
                        if last_point:
                            last_ts, last_p = last_point
                            # if price equal and last point was within 1 hour, skip
                            if float(last_p) == float(price) and int(time.time()) - int(last_ts) < 3600:
                                should_insert = False
                        if should_insert:
                            # use new save_price_point which applies deduplication and capping
                            # Добавляем в батч для пакетного сохранения
                            price_points_batch.append((sub_id, float(price), int(time.time()), url))
                            logger.info(f"Collected price point for batch: sub={sub_id}, price={price}")
                    except Exception:
                        logger.exception("Failed to store price point for sub %s", sub_id)

                    update_last_price(sub_id, price)

            except Exception as e:
                sid = locals().get('sub_id', 'unknown')
                logger.exception("check_all inner error for sub %s: %s", sid, e)

    tasks = [process(s) for s in subs]
    await asyncio.gather(*tasks)

    # ПАКЕТНОЕ СОХРАНЕНИЕ всех собранных точек цены
    if price_points_batch:
        try:
            await asyncio.to_thread(save_price_points_batch, price_points_batch)
            logger.info("Batch saved %d price points", len(price_points_batch))
        except Exception as e:
            logger.exception("Failed to batch save price points: %s", e)
            # Fallback: сохраняем по одной
            for sub_id, price, ts, url in price_points_batch:
                try:
                    save_price_point(sub_id, price, ts)
                except Exception as fallback_e:
                    logger.error("Fallback save failed for sub %s: %s", sub_id, fallback_e)

    # ОТПРАВКА ГРУППОВЫХ УВЕДОМЛЕНИЙ
    await send_grouped_notifications(grouped_notifications)

    logger.info("Scheduler job finished — processed %d, alerted %d", processed_count, alerted_count)

async def start_scheduler_async(delay: float = 1.0):
    """Асинхронно стартует планировщик после того, как event loop запущен.
    Настраиваем AsyncIOScheduler на текущий running loop и добавляем корутину
    `check_all` как задачу-джобу, чтобы APScheduler вызывал её внутри event loop.
    """
    await asyncio.sleep(delay)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.exception("No running event loop, cannot start scheduler")
        return

    # Ensure scheduler uses the active event loop so coroutine jobs run in it
    try:
        scheduler.configure(event_loop=loop)
    except Exception:
        # configure may not be necessary for some versions but is harmless to attempt
        logger.debug("scheduler.configure(event_loop=loop) failed or not needed", exc_info=True)

    # Add job: schedule coroutine `check_all` to run every 60 minutes. Use next_run_time now
    # so an immediate check occurs (after we've configured the loop).
    try:
        scheduler.add_job(check_all, "interval", minutes=60, next_run_time=datetime.now())
        # Add daily backup job at 3:00 AM
        scheduler.add_job(backup_database, "cron", hour=3, minute=0)
        scheduler.start()
        logger.info("Scheduler started (async) - includes daily backups")
    except Exception:
        logger.exception("Failed to start scheduler or add job")

# --- admin functions
def is_admin(user_id: int) -> bool:
    """Check if user is admin"""
    return user_id in ADMIN_IDS

async def cmd_admin(message: types.Message):
    """Admin commands handler"""
    user_id = message.from_user.id
    if not is_admin(user_id):
        await message.answer(t(user_id, "admin_access_denied"))
        return

    args = message.text.split()
    if len(args) < 2:
        await message.answer(t(user_id, "admin_commands"), parse_mode="HTML")
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
    else:
        await message.answer(t(user_id, "admin_unknown_command"))

async def admin_stats(message: types.Message):
    """Show comprehensive bot statistics"""
    try:
        # Получаем подробную статистику
        report = Analytics.get_full_report()

        # Ограничение на длину сообщения Telegram (4096 символов)
        if len(report) > 4000:
            # Разбиваем на части
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

            # Отправляем по частям
            for i, part in enumerate(parts[:3]):  # Максимум 3 сообщения
                await message.answer(part, parse_mode="HTML")
                if i < len(parts) - 1:
                    await asyncio.sleep(0.5)  # Небольшая пауза между сообщениями
        else:
            await message.answer(report, parse_mode="HTML")

    except Exception as e:
        logger.exception("Error in admin_stats: %s", e)
        await message.answer(f"❌ Ошибка при получении статистики: {e}")

async def admin_broadcast(message: types.Message, text: str):
    """Broadcast message to all users"""
    try:
        import sqlite3

        conn = sqlite3.connect(DB)
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

                # Update status every 10 users
                if sent_count % 10 == 0:
                    await status_msg.edit_text(f"📤 Отправлено: {sent_count}/{len(users)}")

                # Small delay to avoid rate limits
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

        # Parse command arguments
        args = message.text.split()
        target_user_id = None

        if len(args) > 2 and args[1] == "users" and args[2].isdigit():
            target_user_id = int(args[2])

        if target_user_id:
            # Show detailed info about specific user
            await admin_user_details(message, target_user_id)
        else:
            # Show interactive list of all users
            await admin_users_list(message)

    except Exception as e:
        logger.exception("Error in admin_users: %s", e)
        await message.answer(f"❌ {t(message.from_user.id, 'error_generic')}: {e}")

async def admin_users_list(message: types.Message):
    """Show list of active users"""
    try:
        from database import get_connection

        admin_user_id = message.from_user.id

        with get_connection() as conn:
            cursor = conn.cursor()

            # Проверяем, существует ли колонка created_at
            cursor.execute("PRAGMA table_info(users)")
            columns = cursor.fetchall()
            column_names = [col[1] for col in columns]

            if 'created_at' in column_names:
                # Если колонка существует, используем ее
                query = """
                    SELECT u.user_id, u.language, u.created_at, COUNT(s.id) as subs_count
                    FROM users u
                    LEFT JOIN subscriptions s ON u.user_id = s.user_id
                    GROUP BY u.user_id, u.language, u.created_at
                    ORDER BY u.created_at DESC
                    LIMIT 50
                """
            else:
                # Если колонки нет, используем альтернативный запрос
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

        # Create inline keyboard with user buttons
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

        keyboard = InlineKeyboardMarkup(inline_keyboard=[])
        users_text = f"👥 <b>{t(admin_user_id, 'admin_users_title')}</b>\n\n"

        for user_data in users:
            if len(user_data) == 4:
                # С колонкой created_at
                user_id, language, created_at, subs_count = user_data
                created_str = datetime.fromtimestamp(created_at).strftime('%d.%m.%Y %H:%M')
                user_line = f"🆔 <code>{user_id}</code> | 🌐 {language.upper()} | 📦 {subs_count} | 📅 {created_str}"
            else:
                # Без колонки created_at
                user_id, language, subs_count = user_data
                user_line = f"🆔 <code>{user_id}</code> | 🌐 {language.upper()} | 📦 {subs_count}"

            users_text += user_line + "\n"

            # Add button for this user
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

        admin_user_id = message.from_user.id

        with get_connection() as conn:
            cursor = conn.cursor()

            # Проверяем, существует ли колонка created_at
            cursor.execute("PRAGMA table_info(users)")
            columns = cursor.fetchall()
            column_names = [col[1] for col in columns]

            if 'created_at' in column_names:
                # Если колонка существует, используем ее
                query = """
                    SELECT u.user_id, u.language, u.created_at, COUNT(s.id) as subs_count
                    FROM users u
                    LEFT JOIN subscriptions s ON u.user_id = s.user_id
                    GROUP BY u.user_id, u.language, u.created_at
                    ORDER BY u.created_at DESC
                    LIMIT 50
                """
            else:
                # Если колонки нет, используем альтернативный запрос
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

        # Create inline keyboard with user buttons
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

        users_text = f"👥 <b>{t(admin_user_id, 'admin_users_title')}</b>\n\n"
        users_text += f"📊 <b>{t(admin_user_id, 'admin_users_count')}:</b> {len(users)}\n\n"

        keyboard = InlineKeyboardMarkup(inline_keyboard=[])

        for user_data in users:
            if len(user_data) == 4:
                # С колонкой created_at
                user_id, language, created_at, subs_count = user_data
                created_str = datetime.fromtimestamp(created_at).strftime('%d.%m.%Y %H:%M')
                user_info = f"🆔 {user_id} | 🌐 {language.upper()} | 📦 {subs_count} | 📅 {created_str}"
            else:
                # Без колонки created_at
                user_id, language, subs_count = user_data
                user_info = f"🆔 {user_id} | 🌐 {language.upper()} | 📦 {subs_count}"

            # Add button for each user
            button = InlineKeyboardButton(
                text=f"👤 {user_id} ({subs_count} subs)",
                callback_data=f"user_details:{user_id}"
            )
            keyboard.inline_keyboard.append([button])

        # Add refresh button
        refresh_button = InlineKeyboardButton(
            text=f"🔄 {t(admin_user_id, 'admin_users_refresh')}",
            callback_data="admin_users_refresh"
        )
        keyboard.inline_keyboard.append([refresh_button])

        await message.edit_text(users_text, reply_markup=keyboard, parse_mode="HTML")

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

            # Check if created_at column exists
            cursor.execute("PRAGMA table_info(users)")
            columns = cursor.fetchall()
            column_names = [col[1] for col in columns]
            has_created_at = 'created_at' in column_names

            # Get user basic info
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

            # Get user's subscriptions
            subscriptions = get_user_subscriptions(user_id)

            # Build detailed user info
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

            # Show subscriptions if any
            if subscriptions:
                user_text += f"📋 <b>{t(message.from_user.id, 'admin_user_subs_list')}:</b>\n\n"

                for i, sub in enumerate(subscriptions[:10], 1):  # Show max 10 subscriptions
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

        # Split message if too long (Telegram limit is 4096 chars)
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

            # Send in parts
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

            # Check if created_at column exists
            cursor.execute("PRAGMA table_info(users)")
            columns = cursor.fetchall()
            column_names = [col[1] for col in columns]
            has_created_at = 'created_at' in column_names

            # Get user basic info
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

            # Try to get Telegram user info
            telegram_user_info = ""
            try:
                # Get user info from Telegram (this might not work if user blocked the bot)
                chat_member = await bot.get_chat_member(chat_id=target_user_id, user_id=target_user_id)
                telegram_user = chat_member.user

                # Build full name
                full_name = ""
                if telegram_user.first_name:
                    full_name = telegram_user.first_name
                if telegram_user.last_name:
                    full_name += f" {telegram_user.last_name}"
                full_name = full_name.strip() or "Неизвестно"

                # Username
                username = f"@{telegram_user.username}" if telegram_user.username else "Не установлен"

                # Premium status
                premium_status = "⭐ Да" if getattr(telegram_user, 'is_premium', False) else "Обычный"

                # Language from Telegram
                telegram_lang = getattr(telegram_user, 'language_code', 'Неизвестно')

                telegram_user_info = f"""
👨‍💼 <b>Имя:</b> {full_name}
📱 <b>Username:</b> {username}
🌐 <b>Язык Telegram:</b> {telegram_lang}
⭐ <b>Премиум:</b> {premium_status}"""

            except Exception as e:
                logger.warning(f"Could not get Telegram user info for {target_user_id}: {e}")
                telegram_user_info = "\n⚠️ <b>Информация из Telegram недоступна</b> (пользователь мог заблокировать бота)"

            # Get user's subscriptions
            subscriptions = get_user_subscriptions(user_id)

            # Build detailed user info
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

                for sub in subscriptions[:10]:  # Show first 10 subscriptions
                    try:
                        (sid, uid, url, mode, last_price, product_title, product_image,
                         min_price, max_price, notify_percent, notify_interval, last_notify_time, price_alert) = sub
                    except ValueError:
                        # Fallback for old subscriptions
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

        # Create keyboard with actions
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

        # Split message if too long (Telegram limit is 4096 chars)
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

            # Send in parts
            for i, part in enumerate(parts):
                if i == 0:
                    await message.edit_text(part, parse_mode="HTML")
                else:
                    await message.answer(part, parse_mode="HTML")
                    await asyncio.sleep(0.5)

            # Send keyboard as separate message
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

        conn = sqlite3.connect(DB)
        cursor = conn.cursor()

        # Count before cleanup
        cursor.execute("SELECT COUNT(*) FROM price_history WHERE timestamp < ?", (int(time.time()) - 30*24*3600,))
        old_price_points = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM users WHERE user_id NOT IN (SELECT DISTINCT user_id FROM subscriptions)")
        inactive_users = cursor.fetchone()[0]

        # Cleanup old price history (older than 30 days)
        cursor.execute("DELETE FROM price_history WHERE timestamp < ?", (int(time.time()) - 30*24*3600,))

        # Cleanup users without subscriptions (older than 90 days)
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

async def admin_backup(message: types.Message):
    """Manual database backup"""
    try:
        timestamp = int(time.time())
        backup_path = f"backups/db_backup_{timestamp}.db"

        # Create backups directory if not exists
        Path("backups").mkdir(exist_ok=True)

        # Copy database
        shutil.copy2(DB, backup_path)

        # Clean old backups (keep last 7)
        backup_files = list(Path("backups").glob("db_backup_*.db"))
        backup_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)

        if len(backup_files) > 7:
            for old_file in backup_files[7:]:
                old_file.unlink()

        backup_size = Path(backup_path).stat().st_size / 1024 / 1024  # MB

        await message.answer(
            f"✅ <b>БЭКАП СОЗДАН</b>\n\n"
            f"📁 Файл: {backup_path}\n"
            f"📊 Размер: {backup_size:.1f} MB\n"
            f"🗂️ Всего бэкапов: {len(backup_files[:7])}",
            parse_mode="HTML"
        )

    except Exception as e:
        logger.exception("Error in admin_backup: %s", e)
        await message.answer(f"❌ Ошибка при создании бэкапа: {e}")

async def submit_user_report(user_id: int, report_text: str, message: types.Message):
    """Submit user report to admin"""
    try:
        # Get user info from database
        from database import get_connection
        user_lang = "ru"
        user_created = None
        with get_connection() as conn:
            cursor = conn.cursor()
            # Check if created_at column exists
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

        # Get user subscription count
        subs_count = len(get_user_subscriptions(user_id))

        # Get detailed user info from Telegram
        user_info = ""
        if message and message.from_user:
            user = message.from_user

            # Build full name
            full_name = ""
            if user.first_name:
                full_name = user.first_name
            if user.last_name:
                full_name += f" {user.last_name}"
            full_name = full_name.strip() or "Не указано"

            # Username
            username = f"@{user.username}" if user.username else "Не установлен"

            # Premium status
            premium_status = "⭐ Да" if getattr(user, 'is_premium', False) else "Обычный"

            # Language from Telegram
            telegram_lang = getattr(user, 'language_code', 'Неизвестно')

            # Registration date
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

        # Format report for admin
        admin_report = f"""
📋 <b>НОВЫЙ РЕПОРТ ОТ ПОЛЬЗОВАТЕЛЯ</b>

👤 <b>ID:</b> <code>{user_id}</code>
🌐 <b>Язык бота:</b> {user_lang}
📊 <b>Подписок:</b> {subs_count}{user_info}

💬 <b>Сообщение:</b>
{report_text}

<i>Используйте /admin respond {user_id} [текст ответа] для ответа</i>
"""

        # Send to all admins
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(admin_id, admin_report, parse_mode="HTML")
            except Exception as e:
                logger.warning(f"Failed to send report to admin {admin_id}: {e}")

        # Confirm to user (if message object provided)
        if message:
            await message.answer(t(user_id, "report_sent"))

    except Exception as e:
        logger.exception("Error submitting user report: %s", e)
        if message and hasattr(message, 'answer'):
            try:
                await message.answer(t(user_id, "error_generic"))
            except Exception:
                pass  # Ignore errors when sending error messages

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

        # Send response to user
        try:
            response_message = f"""
💬 <b>ОТВЕТ АДМИНИСТРАТОРА</b>

{response_text}

<i>Если у вас есть дополнительные вопросы, используйте /report</i>
"""
            await bot.send_message(target_user_id, response_message, parse_mode="HTML")

            # Confirm to admin
            await message.answer(f"✅ Ответ отправлен пользователю {target_user_id}")

        except Exception as e:
            logger.warning(f"Failed to send response to user {target_user_id}: {e}")
            await message.answer(f"❌ Не удалось отправить ответ пользователю {target_user_id}")

    except ValueError:
        await message.answer("❌ Неверный формат user_id")
    except Exception as e:
        logger.exception("Error in admin_respond: %s", e)
        await message.answer(f"❌ Ошибка: {e}")

# --- Automatic backups
async def backup_database():
    """Create daily database backup"""
    try:
        timestamp = int(time.time())
        backup_path = f"backups/db_backup_{timestamp}.db"

        # Create backups directory if not exists
        Path("backups").mkdir(exist_ok=True)

        # Copy database
        shutil.copy2(DB, backup_path)

        # Clean old backups (keep last 7)
        backup_files = list(Path("backups").glob("db_backup_*.db"))
        backup_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)

        if len(backup_files) > 7:
            for old_file in backup_files[7:]:
                old_file.unlink()

        logger.info(f"Daily backup created: {backup_path} (kept {len(backup_files[:7])} backups)")
    except Exception as e:
        logger.exception(f"Error in automatic backup: {e}")

# --- Smart recommendations system
def analyze_user_preferences(user_id: int) -> Dict[str, Any]:
    """Analyze user's product preferences based on subscriptions"""
    try:
        from database import get_connection

        with get_connection() as conn:
            cursor = conn.cursor()

            # Get all user subscriptions
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
                # Extract brand from URL (first part of path)
                url_parts = url.replace('https://www.trendyol.com/', '').split('/')
                if len(url_parts) > 0:
                    brand = url_parts[0].lower()
                    if brand and not brand.startswith('p-'):
                        brands.append(brand)

                # Extract keywords from title
                if title:
                    # Enhanced keyword extraction with more categories and brands
                    title_lower = title.lower()

                    # Smartphones & Mobile
                    if any(word in title_lower for word in ['telefon', 'iphone', 'samsung', 'xiaomi', 'huawei', 'oppo', 'vivo', 'realme']):
                        categories.append('smartphones')
                        keywords.extend(['telefon', 'smartphone', 'mobile', 'android', 'ios'])
                        # Extract brand
                        if 'iphone' in title_lower or 'apple' in title_lower:
                            brands.append('apple')
                        elif 'samsung' in title_lower:
                            brands.append('samsung')
                        elif 'xiaomi' in title_lower:
                            brands.append('xiaomi')

                    # Home Appliances
                    if any(word in title_lower for word in ['robot', 'supurge', 'vacuum', 'cleaner', 'dyson', 'irobot', 'roomba']):
                        categories.append('home_appliances')
                        keywords.extend(['robot', 'supurge', 'vacuum', 'cleaner', 'home'])
                        if 'dyson' in title_lower:
                            brands.append('dyson')

                    # Cosmetics & Beauty
                    if any(word in title_lower for word in ['krema', 'kosmetik', 'kozmetik', 'cream', 'moisturizer', 'makyaj', 'parfum', 'şampuan']):
                        categories.append('cosmetics')
                        keywords.extend(['krema', 'cream', 'cosmetic', 'beauty', 'skincare'])

                    # Accessories
                    if any(word in title_lower for word in ['kilif', 'case', 'cover', 'kulaklik', 'headphone', 'earbuds']):
                        categories.append('accessories')
                        keywords.extend(['kilif', 'case', 'cover', 'accessory'])

                    # Fashion & Clothing
                    if any(word in title_lower for word in ['tisort', 'gomlek', 'pantolon', 'ayakkabi', 'shirt', 'pants', 'shoes']):
                        categories.append('fashion')
                        keywords.extend(['fashion', 'clothing', 'wear'])

                    # Electronics
                    if any(word in title_lower for word in ['kulaklik', 'headphone', 'earbuds', 'mouse', 'keyboard', 'monitor']):
                        categories.append('electronics')
                        keywords.extend(['electronics', 'gadget', 'tech'])

            # Count most common categories and brands
            from collections import Counter
            category_counts = Counter(categories)
            brand_counts = Counter(brands)

            return {
                "has_subscriptions": True,
                "categories": category_counts.most_common(3),  # Top 3 categories
                "brands": brand_counts.most_common(3),        # Top 3 brands
                "keywords": list(set(keywords)),              # Unique keywords
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

        # Personalized recommendation logic
        user_brands = [brand.lower() for brand, _ in preferences["brands"]]

        for category, count in preferences["categories"]:
            category_products = [p for p in available_products if p["category"] == category]

            # Prioritize products from user's preferred brands
            preferred_products = []
            other_products = []

            for product in category_products:
                product_brand = product.get("brand", "").lower()
                if product_brand in user_brands:
                    preferred_products.append(product)
                else:
                    other_products.append(product)

            # Mix preferred and other products (70% preferred, 30% other)
            selected_products = []
            preferred_count = min(len(preferred_products), max(1, int(limit * 0.7)))
            other_count = min(len(other_products), limit - preferred_count)

            if preferred_products:
                selected_products.extend(random.sample(preferred_products, min(preferred_count, len(preferred_products))))
            if other_products and len(selected_products) < limit:
                remaining_slots = limit - len(selected_products)
                selected_products.extend(random.sample(other_products, min(other_count, remaining_slots, len(other_products))))

            # Add to recommendations
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

        # If no category-based recommendations, add general popular products
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

        # Shuffle final recommendations for variety
        random.shuffle(recommendations)

        return recommendations[:limit]

    except Exception as e:
        logger.exception(f"Error generating recommendations for {user_id}: {e}")
        return []

def get_available_products() -> List[Dict[str, Any]]:
    """Get list of available products for recommendations"""
    return [
        # Smartphones
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

        # Home Appliances
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

        # Cosmetics
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

        # Fashion
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

        # Electronics
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

# --- New user commands
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

        # Формируем сообщение с текущими алертами
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

            # Кнопки для управления алертом
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

@dp.message(Command("compare"))
async def cmd_compare(message: types.Message):
    """Сравнение цен товаров"""
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

    url1, url2 = args[1], args[2]

    # Валидация URL
    if not (is_trendyol_product_url(url1) and is_trendyol_product_url(url2)):
        await message.answer(t(user_id, "not_product_url"))
        return

    await message.answer(t(user_id, "compare_loading"))

    try:
        # Получаем информацию о товарах параллельно
        price1, title1, image1 = await get_product_info_async(url1)
        price2, title2, image2 = await get_product_info_async(url2)

        if not (price1 and price2):
            await message.answer(t(user_id, "compare_error_no_price"))
            return

        # Формируем сравнение
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
        logger.exception("Error in compare command: %s", e)
        await message.answer(t(user_id, "error_generic"))

@dp.message(Command("recommend"))
async def cmd_recommend(message: types.Message):
    """Show personalized product recommendations"""
    user_id = message.from_user.id
    add_user_if_not_exists(user_id)

    await message.answer(t(user_id, "recommend_loading"))

    try:
        recommendations = await generate_recommendations(user_id, limit=5)

        if not recommendations:
            await message.answer(t(user_id, "recommend_no_data"))
            return

        response = f"🎯 <b>{t(user_id, 'recommend_title')}</b>\n\n"

        keyboard = []

        for i, rec in enumerate(recommendations[:5], 1):
            response += f"{i}. <b>{rec['title']}</b>\n"
            response += f"💰 {rec['price']}\n"
            response += f"📝 {rec['reason']}\n\n"

            # Add button to view product
            keyboard.append([
                InlineKeyboardButton(
                    text=f"🔍 {t(user_id, 'btn_view_product')} {i}",
                    url=rec['url']
                )
            ])

        response += f"💡 {t(user_id, 'recommend_hint')}"

        markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
        await message.answer(response, reply_markup=markup, parse_mode="HTML")

    except Exception as e:
        logger.exception("Error in cmd_recommend: %s", e)
        await message.answer(f"❌ {t(user_id, 'error_generic')}: {e}")

# --- Health checks
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

        # Additional info
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
        # Database connection
        import sqlite3
        conn = sqlite3.connect(DB, timeout=5)
        conn.execute("SELECT 1")
        conn.close()
        results["База данных"] = True
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        results["База данных"] = False

    try:
        # Bot connectivity
        await bot.get_me()
        results["Бот (Telegram API)"] = True
    except Exception as e:
        logger.error(f"Bot health check failed: {e}")
        results["Бот (Telegram API)"] = False

    try:
        # Scheduler status
        if hasattr(scheduler, 'running') and scheduler.running:
            results["Планировщик задач"] = True
        else:
            results["Планировщик задач"] = False
    except Exception as e:
        logger.error(f"Scheduler health check failed: {e}")
        results["Планировщик задач"] = False

    try:
        # Scraper functionality (test with a real product URL)
        from scraper import get_price_async
        # Test with a known working product URL (Cream Co moisturizer)
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

    # Update last check time
    last_health_check = int(time.time())

    return results

# --- main
async def main():
    # Регистрируем антиспам middleware
    dp.message.middleware(AntiSpamMiddleware())
    dp.callback_query.middleware(AntiSpamMiddleware())
    # Start scheduler after loop is running
    asyncio.create_task(start_scheduler_async())
    # Ensure no webhook is set (prevents TelegramConflictError when polling)
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Webhook deleted / cleared (if existed)")
    except Exception as e:
        logger.warning("Failed to delete webhook (may be fine): %s", e)

    # Register handlers based on architecture
    use_new_handlers = USE_NEW_HANDLERS
    if use_new_handlers:
        logger.info("Using new handler architecture")
        try:
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
            logger.error(f"Failed to register new handlers: {e}")
            logger.info("Falling back to legacy handlers")
            use_new_handlers = False

    if not use_new_handlers:
        logger.info("Using legacy handler architecture")
        # Register old handlers
        dp.message.register(cmd_start_old, Command("start"))
        dp.message.register(cmd_help_old, Command("help"))
        dp.message.register(cmd_mysubs_cmd_old, Command("mysubs"))
        dp.message.register(cmd_unsubscribe_old, Command("unsubscribe"))
        dp.message.register(cmd_stats_old, Command("stats"))
        dp.message.register(cmd_all_list_old, Command("all_list"))
        dp.message.register(cmd_top_drops_old, Command("top_drops"))
        dp.message.register(handle_url_old, lambda m: m.text and ('trendyol.com' in (m.text or '').lower() or 'ty.gl/' in (m.text or '').lower()))

    # Register admin commands
    dp.message.register(cmd_admin, Command("admin"))
    dp.message.register(cmd_health, Command("health"))

    logger.info("Bot polling started")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
