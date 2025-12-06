import asyncio
import json
import logging
from typing import Optional, List, Tuple
from datetime import datetime, timedelta
import io
import re
import os
import csv

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton, CallbackQuery
)

from config import BOT_TOKEN, _check_bot_token
import time
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
    update_user_settings
)
from database import update_subscription_meta
from database import add_price_point, get_price_history, get_last_price_point, save_price_point, get_local_price_history
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
def normalize_url(url: str) -> str:
    u = (url or "").strip()
    u = u.split("#", 1)[0]
    u = u.split("?", 1)[0]
    if u.endswith("/"):
        u = u[:-1]
    return u

def is_trendyol_product_url(u: str) -> bool:
    ul = (u or "").lower()
    return ("trendyol.com" in ul) and ("/p/" in ul or "-p-" in ul)


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


def is_trendyol_product_url(u: str) -> bool:
    ul = (u or "").lower()
    return ("trendyol.com" in ul) and ("/p/" in ul or "-p-" in ul)

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
            [KeyboardButton(text=t(user_id, "btn_trending")), KeyboardButton(text=t(user_id, "btn_language"))],
            [KeyboardButton(text=t(user_id, "btn_unsubscribe"))]
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
        ]
    ])

# start
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
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
@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer(t(message.from_user.id, "help_text"))

@dp.message(Command("mysubs"))
async def cmd_mysubs_cmd(message: types.Message):
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
        _, _, url, _, _, _, _, _, _, _, _, _ = sub
        await message.answer(t(message.from_user.id, "history_fetching"))
        # First try local DB history
        db_hist = get_price_history(sid, limit=1000)
        if db_hist and len(db_hist) >= 2:
            # convert (ts, price) -> [(iso_date, price), ...]
            hist = [(datetime.fromtimestamp(r[0]).isoformat(), r[1]) for r in db_hist]
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

@dp.message(Command("unsubscribe"))
async def cmd_unsubscribe(message: types.Message):
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
    except Exception:
        await message.answer(t(message.from_user.id, "error_generic"))

@dp.message(Command("price_alert"))
async def cmd_price_alert(message: types.Message):
    """Установить целевую цену для уведомлений"""
    parts = (message.text or "").split()
    if len(parts) < 3:
        await message.answer(
            "Используйте: /price_alert <ID подписки> <Целевая цена>\n"
            "Пример: /price_alert 1 2500\n"
            "Вы получите уведомление когда цена упадет ниже этого значения"
        )
        return
    
    if not parts[1].isdigit():
        await message.answer("ID подписки должен быть числом")
        return
    
    sid = int(parts[1])
    
    try:
        target_price = float(parts[2])
    except ValueError:
        await message.answer("Целевая цена должна быть числом")
        return
    
    if target_price < 0:
        await message.answer("Цена не может быть отрицательной")
        return
    
    sub = get_subscription(sid)
    if not sub:
        await message.answer("Подписка не найдена")
        return
    
    # Безопасная проверка владельца
    if len(sub) >= 2 and sub[1] != message.from_user.id:
        await message.answer("Это не ваша подписка")
        return
    
    try:
        update_subscription_settings(sid, price_alert=target_price)
        current_price = sub[4] if len(sub) > 4 else None
        
        if current_price and current_price <= target_price:
            await message.answer(
                f"✅ Целевая цена установлена: {target_price:.0f}₽\n"
                f"ℹ️ Текущая цена: {current_price:.0f}₽\n"
                f"ℹ️ Цена уже ниже целевой!"
            )
        else:
            await message.answer(
                f"✅ Целевая цена установлена: {target_price:.0f}₽\n"
                f"ℹ️ Вы получите уведомление когда цена упадет ниже этого значения"
            )
    except Exception as e:
        logger.exception("Error setting price_alert: %s", e)
        await message.answer("Ошибка при установке целевой цены")

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
@dp.message(Command("stats"))
async def cmd_stats(message: types.Message):
    """Show price statistics for a subscription"""
    try:
        args = message.text.split()
        if len(args) < 2:
            await message.answer("ℹ️ Использование: /stats <ID>\nПример: /stats 5")
            return
        
        sub_id = int(args[1])
        sub = get_subscription(sub_id)
        
        if not sub:
            await message.answer("❌ Подписка не найдена")
            return
        
        # Проверяем владельца
        if sub[1] != message.from_user.id:
            await message.answer(t(message.from_user.id, "error_not_your_sub"))
            return
        
        from database import get_price_stats
        stats = get_price_stats(sub_id)
        
        if stats['count'] == 0:
            await message.answer("📊 История цен еще не собрана. Попробуйте позже.")
            return
        
        # Форматируем статистику
        curr = f"{stats['current']:.2f}" if stats['current'] else "—"
        min_p = f"{stats['min']:.2f}" if stats['min'] else "—"
        max_p = f"{stats['max']:.2f}" if stats['max'] else "—"
        avg_p = f"{stats['avg']:.2f}" if stats['avg'] else "—"
        
        text = f"""📊 *Статистика цен*

🏷️ ID: {sub_id}
🔗 {sub[2][:50]}...

💰 Текущая: {curr} TL
📉 Минимум: {min_p} TL
📈 Максимум: {max_p} TL
📊 Средняя: {avg_p} TL
📈 Тренд: {stats['trend']}
📅 Дней данных: {stats['days']}
📌 Точек: {stats['count']}
"""
        await message.answer(text, parse_mode="Markdown")
        
    except ValueError:
        await message.answer("❌ ID должен быть числом")
    except Exception as e:
        logger.exception("Stats command error: %s", e)
        await message.answer(f"❌ Ошибка: {e}")

# /all_list - Компактный список всех подписок
@dp.message(Command("all_list"))
async def cmd_all_list(message: types.Message):
    """Show all subscriptions in compact table format"""
    try:
        subs = get_user_subscriptions(message.from_user.id)
        
        if not subs:
            await message.answer(t(message.from_user.id, "no_subs"))
            return
        
        # Форматируем в таблицу
        header = "📋 *Ваши подписки:*\n\n"
        header += "`ID  | Режим      | Цена    | Статус`\n"
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
        text += f"\n\n✅ Всего: {len(subs)} подписок"
        
        await message.answer(text, parse_mode="Markdown")
        
    except Exception as e:
        logger.exception("All list command error: %s", e)
        await message.answer(f"❌ Ошибка: {e}")

# /top_drops - Топ товаров с падением цены
@dp.message(Command("top_drops"))
async def cmd_top_drops(message: types.Message):
    """Show top products with biggest price drops"""
    try:
        from database import get_top_price_drops
        
        drops = get_top_price_drops(message.from_user.id, limit=10)
        
        if not drops:
            await message.answer("📉 Нет данных о падениях цены")
            return
        
        text = "📉 *Топ падений цены за месяц*\n\n"
        
        for i, (sub_id, url, title, curr_price, min_price, drop_pct) in enumerate(drops, 1):
            title_short = (title or "Товар")[:30]
            icon = "🔴" if drop_pct < 0 else "🟢"
            curr_str = f"{curr_price:.0f}" if curr_price else "—"
            min_str = f"{min_price:.0f}" if min_price else "—"
            
            text += f"{i}. {icon} *{drop_pct:+.1f}%* | ID:{sub_id}\n"
            text += f"   {title_short}\n"
            text += f"   Текущая: {curr_str} TL | Минимум: {min_str} TL\n\n"
        
        await message.answer(text, parse_mode="Markdown")
        
    except Exception as e:
        logger.exception("Top drops command error: %s", e)
        await message.answer(f"❌ Ошибка: {e}")


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

# --- callback handler (languages, modes, unsubscribe, history)
@dp.callback_query()
async def callback_handler(cq: CallbackQuery):
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
            except Exception as e:
                logger.exception("Failed to send updated main kb or edit msg: %s", e)
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
            except Exception as e:
                logger.exception("unsubscribe callback error: %s", e)
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
                    hist = [(datetime.fromtimestamp(r[0]).isoformat(), r[1]) for r in db_hist]
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

        await cq.answer()

    except Exception as e:
        logger.exception("callback_handler error: %s", e)
        try:
            await cq.answer(t(user_id, "error_generic"), show_alert=True)
        except:
            pass

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

@dp.message(lambda m: m.text and ('trendyol.com' in (m.text or '').lower()))
async def handle_url(message: types.Message):
    raw = (message.text or "").strip()
    url = normalize_url(raw)
    url_lower = url.lower()
    if "trendyol.com" not in url_lower:
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
    except Exception as e:
        logger.exception("Error fetching product info for subscription: %s", e)
        price, title, image = None, None, None

    # Сохраняем title/image в кэше подписки, если они получены
    try:
        if title or image:
            update_subscription_meta(sub_id, title, image)
    except Exception as e:
        logger.exception("Failed to update subscription meta: %s", e)

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

# --- List subs
@dp.message(lambda m: m.text and (t(m.from_user.id, "btn_subs") == m.text or "мои подпис" in m.text.lower()))
async def cmd_mysubs(message: types.Message):
    subs = get_user_subscriptions(message.from_user.id)
    if not subs:
        await message.answer(t(message.from_user.id, "no_subs"))
        return
    for sub in subs:
        try:
            (sub_id, user_id, url, mode, last_price, product_title, product_image,
             min_price, max_price, notify_percent, notify_interval, last_notify_time, price_alert) = sub
        except ValueError:
            # Fallback для старых подписок
            (sub_id, user_id, url, mode, last_price, product_title, product_image,
             min_price, max_price, notify_percent, notify_interval, last_notify_time) = sub[:12]
            price_alert = None
        lp = f"{last_price} TL" if last_price is not None else t(message.from_user.id, "unknown_price")
        text = t(message.from_user.id, "sub_item").format(id=sub_id, url=url, mode=mode, last_price=lp)
        try:
            await message.answer(text, reply_markup=subscription_controls_kb_for_user(message.from_user.id, sub_id))
        except Exception:
            await message.answer(text)

# --- Trending
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
                except Exception as e:
                    logger.exception("Error fetching product info for sub %s: %s", sub_id, e)
                    price, title, image = None, None, None

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
                        f"Целевая цена: {price_alert:.0f}₽\n"
                        f"Текущая цена: {price:.0f}₽\n"
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
                    # УЛУЧШЕНИЕ: Используем безопасную отправку с таймаутом
                    success = await send_notification_safe(
                        user_id,
                        notification_text,
                        image=image if image else None,
                        timeout_seconds=10.0
                    )
                    
                    if success:
                        alerted_count += 1
                        update_notify_time(sub_id)
                    else:
                        # Проверяем если это блокировка бота
                        try:
                            # Небольшой тест чтобы узнать заблокирован ли бот
                            await asyncio.wait_for(
                                bot.send_message(user_id, "test"),
                                timeout=2.0
                            )
                        except aiogram.exceptions.TelegramForbiddenError:
                            logger.warning("User %d blocked the bot. Removing subscriptions.", user_id)
                            remove_subscriptions_by_user(user_id)
                        except Exception:
                            pass  # Other errors, retry next time

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
                            try:
                                res = save_price_point(sub_id, float(price), int(time.time()))
                                if res > 0:
                                    logger.info(f"Saved price point: sub={sub_id}, price={price}")
                            except Exception:
                                # Fallback to legacy insert
                                add_price_point(sub_id, url, float(price), source='collector')
                    except Exception:
                        logger.exception("Failed to store price point for sub %s", sub_id)

                    update_last_price(sub_id, price)

            except Exception as e:
                sid = locals().get('sub_id', 'unknown')
                logger.exception("check_all inner error for sub %s: %s", sid, e)

    tasks = [process(s) for s in subs]
    await asyncio.gather(*tasks)
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
        scheduler.start()
        logger.info("Scheduler started (async)")
    except Exception:
        logger.exception("Failed to start scheduler or add job")

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

    logger.info("Bot polling started")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
