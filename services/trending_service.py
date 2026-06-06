"""UI helpers and lightweight state for Trendyol trends."""

import html
import re
import time
from typing import Dict, List, Optional, Set, Tuple

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from localization import t

TrendItem = Tuple[str, Optional[float], str]
TRENDING_ITEMS_LIMIT = 5

TREND_SEARCH_AWAIT: Set[int] = set()
TRENDING_RESULT_CACHE_TTL_SECONDS = 10 * 60
TRENDING_RESULT_CACHE: Dict[str, Tuple[float, List[TrendItem]]] = {}

_TRENDING_TITLE_NOISE_RE = re.compile(
    r"(?:h[\u0131iI\u0130]zl[\u0131iI\u0130]\s*bak[\u0131iI\u0130][\u015fs\u015eS]|hizli\s*bakis|quick\s*view)",
    re.IGNORECASE,
)
_TRENDING_TITLE_PREFIX_RE = re.compile(
    r"^\s*En\s+(?:\u00c7ok|Cok)\s+(?:Satan|Ziyaret\s+Edilen)\s+\d+\.\s+(?:\u00dcr\u00fcn|Urun)\s+",
    re.IGNORECASE,
)
_TRENDING_TITLE_LABEL_RE = re.compile(
    r"\b(?:Az\u0259rbaycana\s+\u00d6z\u0259l\s+Endirim|Kargo\s+Bedava|\u0259lav\u0259\s+endirim|Sepete\s+Ekle)\b",
    re.IGNORECASE,
)
_TRENDING_TITLE_RATING_SUFFIX_RE = re.compile(r"\s+\d(?:[.,]\d)?\s*\(\s*\d+\s*\).*$")
_TRENDING_TITLE_PRICE_SUFFIX_RE = re.compile(
    r"\s+(?:-?%\d+(?:[.,]\d+)?\s*)?"
    r"(?:\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)\s*"
    r"(?:TL|TRY|\u20ba|AZN|\u20bc).*$",
    re.IGNORECASE,
)
_TRENDING_TITLE_DISCOUNT_SUFFIX_RE = re.compile(r"\s+-?%\d+(?:[.,]\d+)?\s*$")
_TRENDING_TITLE_STOCK_SUFFIX_RE = re.compile(r"(?:\s+\bVar\b)+\s*$", re.IGNORECASE)


def trending_cache_key(scope: str, value: str = "") -> str:
    normalized_scope = re.sub(r"\s+", "_", str(scope or "").strip().lower())
    normalized_value = re.sub(r"\s+", " ", str(value or "").strip().lower())
    return f"{normalized_scope}:{normalized_value}" if normalized_value else normalized_scope


def get_cached_trending_items(cache_key: str) -> Optional[List[TrendItem]]:
    cached = TRENDING_RESULT_CACHE.get(cache_key)
    if cached is None:
        return None

    created_at, items = cached
    if time.time() - created_at > TRENDING_RESULT_CACHE_TTL_SECONDS:
        TRENDING_RESULT_CACHE.pop(cache_key, None)
        return None

    return list(items)


def set_cached_trending_items(cache_key: str, items: List[TrendItem]) -> None:
    if not items:
        return
    TRENDING_RESULT_CACHE[cache_key] = (time.time(), list(items))


def clean_trending_title(title: Optional[str], url: str = "") -> str:
    raw = (title or "").replace("\u00A0", " ").strip()
    if not raw:
        return url
    raw = _TRENDING_TITLE_NOISE_RE.sub(" ", raw)
    raw = _TRENDING_TITLE_PREFIX_RE.sub(" ", raw)
    raw = _TRENDING_TITLE_RATING_SUFFIX_RE.sub(" ", raw)
    raw = _TRENDING_TITLE_LABEL_RE.sub(" ", raw)
    raw = _TRENDING_TITLE_PRICE_SUFFIX_RE.sub(" ", raw)
    raw = _TRENDING_TITLE_DISCOUNT_SUFFIX_RE.sub(" ", raw)
    raw = _TRENDING_TITLE_STOCK_SUFFIX_RE.sub(" ", raw)
    raw = re.sub(r"\s+", " ", raw).strip(" -|\u2022\u00b7")
    return raw or url


def _short_title(title: Optional[str], url: str, limit: int = 90) -> str:
    raw = clean_trending_title(title, url)
    raw = re.sub(r"\s+", " ", raw)
    if len(raw) <= limit:
        return raw
    return raw[: max(0, limit - 3)].rstrip() + "..."


def _format_price_amount(price: float) -> str:
    value = float(price)
    if abs(value - round(value)) < 0.005:
        return f"{value:.0f}"
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _format_price_for_user(user_id: int, price: Optional[float]) -> str:
    if price is None:
        return t(user_id, "unknown_price")
    try:
        currency = getattr(price, "currency", None) or "TL"
        return f"{_format_price_amount(float(price))} {currency}"
    except (TypeError, ValueError):
        return t(user_id, "unknown_price")


def trending_menu_kb(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=t(user_id, "trending_btn_all"), callback_data="trend:all"),
            InlineKeyboardButton(text=t(user_id, "trending_btn_category"), callback_data="trend:catmenu"),
            InlineKeyboardButton(text=t(user_id, "trending_btn_search"), callback_data="trend:search"),
        ],
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
        [
            InlineKeyboardButton(text=t(user_id, "trending_btn_back"), callback_data="trend:menu"),
        ],
    ])


def format_trending_items(user_id: int, items: List[TrendItem]) -> str:
    lines = []
    for index, (title, price, url) in enumerate(items[:TRENDING_ITEMS_LIMIT], start=1):
        safe_title = html.escape(_short_title(title, url, limit=96), quote=False)
        price_str = html.escape(_format_price_for_user(user_id, price), quote=False)
        lines.append(
            f"{index}. <b>{safe_title}</b>\n"
            f"   {t(user_id, 'trending_price_label')}: {price_str}"
        )
    return "\n\n".join(lines)


def trending_results_kb(
    user_id: int,
    items: List[TrendItem],
    *,
    refresh_callback: str = "trend:all",
) -> InlineKeyboardMarkup:
    rows = []
    for index, (title, _price, url) in enumerate(items[:TRENDING_ITEMS_LIMIT], start=1):
        safe_url = (url or "").strip()
        if not safe_url.startswith("http"):
            continue
        label = _short_title(title, safe_url, limit=44)
        rows.append([
            InlineKeyboardButton(text=f"{index}. {label}", url=safe_url)
        ])

    rows.extend([
        [
            InlineKeyboardButton(text=t(user_id, "trending_btn_refresh"), callback_data=refresh_callback),
            InlineKeyboardButton(text=t(user_id, "trending_btn_search"), callback_data="trend:search"),
        ],
        [
            InlineKeyboardButton(text=t(user_id, "trending_btn_category"), callback_data="trend:catmenu"),
        ],
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def send_trending_list(bot: Bot, user_id: int, items: List[TrendItem]) -> None:
    if not items:
        await bot.send_message(user_id, t(user_id, "trending_unavailable"))
        return

    await bot.send_message(
        user_id,
        t(user_id, "trending_header") + "\n\n" + format_trending_items(user_id, items),
        reply_markup=trending_results_kb(user_id, items),
        parse_mode="HTML",
    )
