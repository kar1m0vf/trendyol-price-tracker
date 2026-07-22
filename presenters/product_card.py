"""Compact and expanded Telegram product-card presentation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import html
from typing import Callable, Optional

from models.product import ProductSnapshot


Translate = Callable[[str], str]
CARD_TEXT_LIMIT = 1000


@dataclass(frozen=True, slots=True)
class ProductCardView:
    subscription_label: str
    title: str
    url: str
    status_icon: str
    status_text: str
    current_price: Optional[float]
    mode_text: str
    next_notification: str
    unknown_price_text: str
    price_alert: Optional[float] = None
    snapshot: Optional[ProductSnapshot] = None


def _clip(value: object, limit: int) -> str:
    text = " ".join(str(value or "").replace("\u00a0", " ").split())
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)].rstrip() + "…"


def _safe(value: object, limit: int = 160) -> str:
    return html.escape(_clip(value, limit), quote=False)


def _money(value: Optional[float], currency: str, unknown: str) -> str:
    if value is None:
        return _safe(unknown, 80)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return _safe(unknown, 80)

    if abs(number - round(number)) < 0.005:
        amount = f"{number:,.0f}"
    else:
        amount = f"{number:,.2f}".rstrip("0").rstrip(".")
    amount_text = _safe(amount.replace(",", " "), 32)
    return f"{amount_text} {_safe(currency or 'TL', 12)}"


def _discount(snapshot: Optional[ProductSnapshot], current: Optional[float]) -> Optional[float]:
    if snapshot is None:
        return None
    if snapshot.discount_percent is not None:
        try:
            return max(0.0, float(snapshot.discount_percent))
        except (TypeError, ValueError):
            return None
    if current and snapshot.old_price and snapshot.old_price > current:
        return (snapshot.old_price - current) / snapshot.old_price * 100
    return None


def _price_lines(view: ProductCardView, tr: Translate) -> list[str]:
    snapshot = view.snapshot
    current = snapshot.price if snapshot and snapshot.price is not None else view.current_price
    currency = snapshot.currency if snapshot and snapshot.currency else "TL"
    current_text = _money(current, currency, view.unknown_price_text)
    old_price = snapshot.old_price if snapshot else None
    discount = _discount(snapshot, current)

    if old_price is not None and current is not None and old_price > current:
        old_text = _money(old_price, currency, view.unknown_price_text)
        discount_text = f" · −{discount:.1f}%" if discount is not None else ""
        lines = [
            f"💰 {_safe(tr('current_price'), 40)}: <s>{old_text}</s> → <b>{current_text}</b>{discount_text}"
        ]
    else:
        lines = [f"💰 {_safe(tr('current_price'), 40)}: <b>{current_text}</b>"]

    if snapshot and snapshot.basket_price is not None:
        if current is None or abs(float(snapshot.basket_price) - float(current)) >= 0.005:
            lines.append(
                f"🛒 {_safe(tr('product_basket_price'), 45)}: "
                f"<b>{_money(snapshot.basket_price, currency, view.unknown_price_text)}</b>"
            )
    return lines


def _rating_line(snapshot: ProductSnapshot, tr: Translate) -> Optional[str]:
    parts = []
    if snapshot.rating is not None:
        try:
            parts.append(f"<b>{float(snapshot.rating):.1f}</b>/5")
        except (TypeError, ValueError):
            pass
    if snapshot.review_count is not None:
        parts.append(_safe(tr("product_reviews").format(count=int(snapshot.review_count)), 80))
    return "⭐ " + " · ".join(parts) if parts else None


def _seller_line(snapshot: ProductSnapshot, tr: Translate) -> Optional[str]:
    if not snapshot.seller:
        return None
    score = ""
    if snapshot.seller_rating is not None:
        try:
            score = f" · {float(snapshot.seller_rating):.1f}/10"
        except (TypeError, ValueError):
            pass
    return (
        f"🏪 {_safe(tr('product_seller'), 35)}: "
        f"<b>{_safe(snapshot.seller, 70)}</b>{score}"
    )


def _stock_line(snapshot: ProductSnapshot, tr: Translate) -> Optional[str]:
    if snapshot.in_stock is True:
        return f"✅ {_safe(tr('product_in_stock'), 70)}"
    if snapshot.in_stock is False:
        return f"❌ <b>{_safe(tr('product_out_of_stock'), 70)}</b>"
    return None


def _tracking_lines(view: ProductCardView, tr: Translate) -> list[str]:
    lines = [
        f"🔔 {_safe(tr('mode'), 35)}: {_safe(view.mode_text, 80)}",
        f"⏱ {_safe(tr('subscription_card_next'), 50)}: {_safe(view.next_notification, 100)}",
    ]
    if view.price_alert is not None:
        currency = view.snapshot.currency if view.snapshot and view.snapshot.currency else "TL"
        lines.append(
            f"🎯 {_safe(tr('price_alert_label'), 45)}: "
            f"<b>{_money(view.price_alert, currency, view.unknown_price_text)}</b>"
        )
    return lines


def _compact_lines(view: ProductCardView, tr: Translate) -> list[str]:
    snapshot = view.snapshot
    title = snapshot.title if snapshot and snapshot.title else view.title
    lines = [
        f"{view.status_icon} <b>{_safe(view.status_text, 70)}</b> | "
        f"<code>{_safe(view.subscription_label, 25)}</code>",
        f"📦 <b>{_safe(title or view.url, 110)}</b>",
        *_price_lines(view, tr),
    ]

    optional_lines: list[str] = []
    if snapshot:
        rating = _rating_line(snapshot, tr)
        seller = _seller_line(snapshot, tr)
        stock = _stock_line(snapshot, tr)
        if stock and snapshot.in_stock is False:
            optional_lines.append(stock)
        if rating:
            optional_lines.append(rating)
        if seller:
            optional_lines.append(seller)

    tracking_lines = ["", *_tracking_lines(view, tr)]
    kept_optional: list[str] = []
    for line in optional_lines:
        candidate = [*lines, *kept_optional, line, *tracking_lines]
        if len("\n".join(candidate)) <= CARD_TEXT_LIMIT:
            kept_optional.append(line)
    return [*lines, *kept_optional, *tracking_lines]


def _safe_detail_block(
    base_lines: list[str],
    detail_lines: list[str],
    limit: int = CARD_TEXT_LIMIT,
) -> list[str]:
    """Keep the expanded card within Telegram's photo-caption limit."""
    kept: list[str] = []
    for line in detail_lines:
        candidate = "\n".join([*base_lines, "", *kept, line])
        if len(candidate) <= limit:
            kept.append(line)
    return kept


def _expanded_lines(view: ProductCardView, tr: Translate) -> list[str]:
    snapshot = view.snapshot
    lines = _compact_lines(view, tr)
    if snapshot is None:
        lines.extend(["", f"ℹ️ {_safe(tr('product_details_unavailable'), 180)}"])
        return lines

    detail_lines: list[str] = []
    if snapshot.brand:
        detail_lines.append(f"🏷 {_safe(tr('product_brand'), 35)}: <b>{_safe(snapshot.brand, 65)}</b>")

    category = " › ".join(snapshot.category_path) if snapshot.category_path else snapshot.category
    if category:
        detail_lines.append(f"📂 {_safe(tr('product_category'), 35)}: {_safe(category, 110)}")

    if snapshot.selected_variants:
        variants = " · ".join(
            f"{_clip(key, 24)}: {_clip(value, 38)}"
            for key, value in list(snapshot.selected_variants.items())[:4]
        )
        detail_lines.append(f"🎨 {_safe(tr('product_variants'), 35)}: {_safe(variants, 150)}")

    if snapshot.delivery:
        delivery = f"🚚 {_safe(tr('product_delivery'), 35)}: {_safe(snapshot.delivery, 90)}"
        if snapshot.free_shipping:
            delivery += f" · {_safe(tr('product_free_shipping'), 55)}"
        detail_lines.append(delivery)
    elif snapshot.free_shipping:
        detail_lines.append(f"🚚 {_safe(tr('product_free_shipping'), 80)}")

    stock = _stock_line(snapshot, tr)
    if stock and snapshot.in_stock is True:
        detail_lines.append(stock)

    attribute_lines = [
        f"• <b>{_safe(key, 34)}</b>: {_safe(value, 62)}"
        for key, value in list(snapshot.attributes.items())[:4]
    ]
    if attribute_lines:
        detail_lines.extend([f"📋 <b>{_safe(tr('product_characteristics'), 45)}</b>", *attribute_lines])

    try:
        updated = datetime.fromtimestamp(float(snapshot.fetched_at)).strftime("%d.%m %H:%M")
        detail_lines.append(f"🕒 {_safe(tr('product_updated'), 40)}: {updated}")
    except (TypeError, ValueError, OSError, OverflowError):
        pass

    if not detail_lines:
        detail_lines.append(f"ℹ️ {_safe(tr('product_details_unavailable'), 180)}")
    lines.extend(["", *_safe_detail_block(lines, detail_lines)])
    return lines


def render_product_card(view: ProductCardView, tr: Translate, *, expanded: bool = False) -> str:
    """Render a safe HTML card; expanded cards remain valid photo captions."""
    lines = _expanded_lines(view, tr) if expanded else _compact_lines(view, tr)
    return "\n".join(lines)
