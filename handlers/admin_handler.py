"""Admin commands, admin callbacks, and maintenance helpers."""
import asyncio
import html
import logging
import os
import secrets
import shlex
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from aiogram import types
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from analytics import Analytics
from config import ADMIN_IDS, BACKUP_DIR, DATABASE_PATH
from database import (
    create_sqlite_backup,
    get_broken_subscriptions,
    get_bot_text,
    get_user_language,
    get_user_subscriptions,
    set_bot_text,
)
from logging_utils import action_event, actor_label, short_value
from localization import t

from .base import BaseHandler

logger = logging.getLogger(__name__)


def _get_env_int(name: str, default: int, *, min_value: Optional[int] = None, max_value: Optional[int] = None) -> int:
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


DB_BACKUP_KEEP_FILES = _get_env_int("DB_BACKUP_KEEP_FILES", 7, min_value=1, max_value=365)
ADMIN_ACTION_TTL_SECONDS = _get_env_int("ADMIN_ACTION_TTL_SECONDS", 30 * 60, min_value=60, max_value=24 * 3600)
ADMIN_USERS_PAGE_SIZE = _get_env_int("ADMIN_USERS_PAGE_SIZE", 10, min_value=5, max_value=25)

_PENDING_BROADCASTS: Dict[str, Dict[str, Any]] = {}
_PENDING_CLEANUPS: Dict[str, Dict[str, Any]] = {}


class ReportDeliveryError(RuntimeError):
    """Raised when a user report could not be delivered to any admin."""


def _get_runtime_bot():
    for module_name in ("__main__", "bot"):
        module = sys.modules.get(module_name)
        runtime_bot = getattr(module, "bot", None) if module else None
        if runtime_bot is not None:
            return runtime_bot

    raise RuntimeError("Bot runtime is not initialized. Call create_app() first.")


def _safe_html(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=False)


def _user_display_name(
    user_id: int,
    username: Optional[str] = None,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
) -> str:
    full_name = " ".join(part for part in [first_name, last_name] if part).strip()
    if full_name and username:
        return f"{full_name} (@{username})"
    if username:
        return f"@{username}"
    if full_name:
        return full_name
    return f"ID {user_id}"


def _user_display_html(
    user_id: int,
    username: Optional[str] = None,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
) -> str:
    return _safe_html(_user_display_name(user_id, username, first_name, last_name))


def _admin_greeting_name(message: types.Message, user_id: int) -> str:
    user = getattr(message, "from_user", None)
    if user is not None:
        name = _user_display_name(
            user_id,
            getattr(user, "username", None),
            getattr(user, "first_name", None),
            getattr(user, "last_name", None),
        )
        if name != f"ID {user_id}":
            return name

    try:
        from database import get_user_profile

        profile = get_user_profile(user_id) or {}
        return _user_display_name(
            user_id,
            profile.get("username"),
            profile.get("first_name"),
            profile.get("last_name"),
        )
    except Exception:
        logger.debug("Could not load admin profile for greeting", exc_info=True)
        return f"ID {user_id}"


def _user_profile_block(
    *,
    first_name: Optional[str],
    last_name: Optional[str],
    username: Optional[str],
    telegram_language_code: Optional[str],
    is_premium: Optional[int],
    last_seen_at: Optional[int],
    source_label: str,
) -> str:
    full_name = " ".join(part for part in [first_name, last_name] if part).strip() or "Не указано"
    username_text = f"@{username}" if username else "Не установлен"
    lang_text = telegram_language_code or "Неизвестно"
    premium_text = "Да" if is_premium else "Нет"
    last_seen_text = "Неизвестно"
    if last_seen_at:
        try:
            last_seen_text = datetime.fromtimestamp(int(last_seen_at)).strftime("%d.%m.%Y %H:%M")
        except Exception:
            last_seen_text = "Неизвестно"

    return (
        f"\n👨‍💼 <b>Имя:</b> {_safe_html(full_name)}"
        f"\n📱 <b>Username:</b> {_safe_html(username_text)}"
        f"\n🌐 <b>Язык Telegram:</b> {_safe_html(lang_text)}"
        f"\n⭐ <b>Premium:</b> {_safe_html(premium_text)}"
        f"\n🕒 <b>Последняя активность:</b> {_safe_html(last_seen_text)}"
        f"\n💾 <b>Источник профиля:</b> {_safe_html(source_label)}"
    )


def _profile_select_exprs(column_names: List[str]) -> str:
    expressions = []
    for column_name, alias in [
        ("username", "username"),
        ("first_name", "first_name"),
        ("last_name", "last_name"),
        ("telegram_language_code", "telegram_language_code"),
        ("is_premium", "is_premium"),
        ("last_seen_at", "last_seen_at"),
    ]:
        if column_name in column_names:
            expressions.append(f"u.{column_name} AS {alias}")
        else:
            expressions.append(f"NULL AS {alias}")
    return ", ".join(expressions)


def _is_message_not_modified_error(exc: Exception) -> bool:
    return "message is not modified" in str(exc).lower()


def _format_dt(ts: Any, fmt: str = "%d.%m.%Y %H:%M") -> str:
    if not ts:
        return "-"
    try:
        return datetime.fromtimestamp(int(ts)).strftime(fmt)
    except Exception:
        return "-"


def _short_admin_text(value: Any, limit: int = 80) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _format_admin_price(price: Any) -> str:
    if price is None:
        return "-"
    try:
        return f"{float(price):.0f} TL"
    except (TypeError, ValueError):
        return "-"


def _admin_user_button_text(
    row_number: int,
    user_id: int,
    username: Optional[str],
    first_name: Optional[str],
    last_name: Optional[str],
) -> str:
    text = f"{row_number}. {_user_display_name(user_id, username, first_name, last_name)}"
    return text[:61] + "..." if len(text) > 64 else text


def _fetch_admin_users_page(offset: int, limit: int = ADMIN_USERS_PAGE_SIZE) -> Dict[str, Any]:
    from database import get_connection

    offset = max(0, int(offset or 0))
    limit = max(1, int(limit or ADMIN_USERS_PAGE_SIZE))

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(users)")
        columns = cursor.fetchall()
        column_names = [col[1] for col in columns]
        cursor.execute("SELECT COUNT(*) FROM users")
        total_users = int(cursor.fetchone()[0])

        if total_users == 0:
            return {"total": 0, "offset": 0, "limit": limit, "users": []}

        max_offset = ((total_users - 1) // limit) * limit
        offset = min(offset, max_offset)

        created_expr = "u.created_at" if "created_at" in column_names else "0"
        profile_exprs = _profile_select_exprs(column_names)
        order_expr = "u.created_at DESC" if "created_at" in column_names else "u.user_id DESC"
        query = f"""
            SELECT
                u.user_id,
                u.language,
                {created_expr} AS created_at,
                {profile_exprs},
                COUNT(s.id) as subs_count
            FROM users u
            LEFT JOIN subscriptions s ON u.user_id = s.user_id
            GROUP BY u.user_id
            ORDER BY {order_expr}
            LIMIT ? OFFSET ?
        """

        cursor.execute(query, (limit, offset))
        users = cursor.fetchall()

    return {"total": total_users, "offset": offset, "limit": limit, "users": users}


def _build_admin_users_page(admin_user_id: int, offset: int = 0) -> Tuple[str, InlineKeyboardMarkup]:
    page = _fetch_admin_users_page(offset)
    users = page["users"]
    total_users = page["total"]
    offset = page["offset"]
    limit = page["limit"]

    if total_users == 0:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="admin_main_menu")]
        ])
        return t(admin_user_id, "admin_users_none"), keyboard

    page_number = offset // limit + 1
    total_pages = (total_users + limit - 1) // limit
    shown_from = offset + 1
    shown_to = offset + len(users)

    users_text = "👥 <b>Управление пользователями</b>\n\n"
    users_text += f"📊 <b>Всего в базе:</b> {total_users}\n"
    users_text += f"📄 <b>Страница:</b> {page_number}/{total_pages}\n"
    users_text += f"📋 <b>Показано:</b> {shown_from}-{shown_to} из {total_users}\n\n"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[])

    for index, user_data in enumerate(users, start=shown_from):
        (
            user_id,
            language,
            created_at,
            username,
            first_name,
            last_name,
            _telegram_language_code,
            _is_premium,
            last_seen_at,
            subs_count,
        ) = user_data
        users_text += (
            f"{index}. 👤 <b>{_user_display_html(user_id, username, first_name, last_name)}</b> "
            f"| <code>{user_id}</code>\n"
            f"   🌐 {(language or '-').upper()} | 📦 {subs_count} | "
            f"📅 {_format_dt(created_at)} | 🕒 {_format_dt(last_seen_at)}\n"
        )

        keyboard.inline_keyboard.append([
            InlineKeyboardButton(
                text=_admin_user_button_text(index, user_id, username, first_name, last_name),
                callback_data=f"user_details:{user_id}",
            )
        ])

    nav_row = []
    if offset > 0:
        nav_row.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"admin_users_page:{max(0, offset - limit)}"))
    if shown_to < total_users:
        nav_row.append(InlineKeyboardButton(text="➡️ Вперёд", callback_data=f"admin_users_page:{offset + limit}"))
    if nav_row:
        keyboard.inline_keyboard.append(nav_row)

    keyboard.inline_keyboard.extend([
        [
            InlineKeyboardButton(text="🔄 Обновить", callback_data=f"admin_users_refresh:{offset}"),
            InlineKeyboardButton(text="🚫 Проверить блокировки", callback_data="admin_check_blocked"),
        ],
        [
            InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats_refresh"),
            InlineKeyboardButton(text="🏠 Главное меню", callback_data="admin_main_menu"),
        ],
    ])

    return users_text, keyboard


def _new_admin_action_token() -> str:
    return secrets.token_urlsafe(8)


def _purge_expired_actions(store: Dict[str, Dict[str, Any]]) -> None:
    expires_before = time.time() - ADMIN_ACTION_TTL_SECONDS
    for token, payload in list(store.items()):
        if float(payload.get("created_at", 0)) < expires_before:
            store.pop(token, None)


def _store_admin_action(store: Dict[str, Dict[str, Any]], admin_user_id: int, payload: Dict[str, Any]) -> str:
    _purge_expired_actions(store)
    token = _new_admin_action_token()
    store[token] = {
        **payload,
        "admin_user_id": admin_user_id,
        "created_at": time.time(),
    }
    return token


def _pop_admin_action(
    store: Dict[str, Dict[str, Any]],
    token: str,
    admin_user_id: int,
) -> Optional[Dict[str, Any]]:
    _purge_expired_actions(store)
    payload = store.get(token)
    if not payload or payload.get("admin_user_id") != admin_user_id:
        return None
    return store.pop(token, None)


async def _edit_or_answer(message: types.Message, text: str, **kwargs):
    try:
        if hasattr(message, "edit_text"):
            return await message.edit_text(text, **kwargs)
    except Exception:
        logger.debug("Failed to edit admin message, falling back to answer", exc_info=True)
    return await message.answer(text, **kwargs)


def _confirm_keyboard(confirm_data: str, cancel_data: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Подтвердить", callback_data=confirm_data),
            InlineKeyboardButton(text="🚫 Отмена", callback_data=cancel_data),
        ],
        [InlineKeyboardButton(text="🏠 Админ-панель", callback_data="admin_main_menu")],
    ])


def _extract_admin_command(message_text: Optional[str]) -> Tuple[str, str]:
    raw_text = (message_text or "").strip()
    parts = raw_text.split(maxsplit=2)
    if len(parts) < 2:
        return "", ""
    command = parts[1].lower()
    tail = parts[2].strip() if len(parts) > 2 else ""
    return command, tail

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
    action_event("ADMIN", "opened admin panel", admin=user_id)

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

    keyboard.inline_keyboard.insert(2, [
        InlineKeyboardButton(text="⚠️ Битые товары", callback_data="admin_broken_subs"),
        InlineKeyboardButton(text="💚 Health", callback_data="admin_health"),
    ])

    greeting_name = _safe_html(_admin_greeting_name(message, user_id))
    welcome_text = "🚀 <b>Панель администратора</b>\n\n"
    welcome_text += f"👋 Добро пожаловать, <b>{greeting_name}</b>.\n"
    welcome_text += f"🆔 Ваш ID: <code>{user_id}</code>\n\n"
    welcome_text += "Выберите действие из меню ниже или используйте текстовые команды.\n\n"
    welcome_text += "<b>⚠️ Важно:</b> Все действия логируются для безопасности."

    await message.answer(welcome_text, reply_markup=keyboard, parse_mode="HTML")

async def cmd_admin(message: types.Message):
    """Admin commands handler"""
    user_id = message.from_user.id
    if not is_admin(user_id):
        logger.warning(f"Access denied for user_id={user_id} in cmd_admin")
        await message.answer(t(user_id, "admin_access_denied"))
        return

    command, tail = _extract_admin_command(message.text)
    logger.debug("cmd_admin called by user_id=%s command=%r", user_id, command or "menu")
    action_event("ADMIN", "command received", admin=actor_label(message.from_user), command=command or "menu")
    if not command:

        await admin_main_menu(message)
        return

    if command == "stats":
        await admin_stats(message)
    elif command == "broadcast":
        if not tail:
            await message.answer("❌ Укажите сообщение: <code>/admin broadcast текст</code>", parse_mode="HTML")
            return
        await admin_broadcast(message, tail)
    elif command == "users":
        await admin_users(message)
    elif command == "cleanup":
        await admin_cleanup(message)
    elif command == "backup":
        await admin_backup(message)
    elif command == "respond":
        await admin_respond(message)
    elif command == "recommend":
        try:
            args = shlex.split(message.text or "")
        except ValueError as e:
            if tail.lower().startswith("text"):
                args = ["/admin", "recommend", "text"]
            else:
                await message.answer(
                    f"❌ Не удалось разобрать команду: {_safe_html(e)}\n"
                    "Проверьте кавычки в названии или ссылке.",
                    parse_mode="HTML",
                )
                return
        await admin_recommend(message, args[2:] if len(args) > 2 else [])
    elif command == "blocked":
        await admin_check_blocked(message)
    elif command in {"broken", "broken_subs", "failures"}:
        await admin_broken_subscriptions(message)
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

async def admin_broken_subscriptions(message: types.Message):
    """Show subscriptions whose price checks are currently failing."""
    admin_user_id = _get_request_user_id(message)
    if not is_admin(admin_user_id):
        await message.answer(t(admin_user_id, "admin_access_denied"))
        return

    rows = get_broken_subscriptions(limit=30, min_fail_count=1)
    action_event(
        "ADMIN",
        "opened broken subscriptions",
        admin=admin_user_id,
        subscriptions=len(rows),
    )

    keyboard_rows = []
    base_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="admin_broken_subs")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="admin_main_menu")],
    ])

    if not rows:
        await _edit_or_answer(
            message,
            "✅ <b>Битые товары</b>\n\nПодписок с неудачными проверками цены сейчас нет.",
            reply_markup=base_keyboard,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        return

    lines = [
        f"⚠️ <b>Битые товары ({len(rows)})</b>",
        "",
        "Подписки, где последняя проверка цены завершилась неудачно.",
    ]

    for index, row in enumerate(rows, start=1):
        sub_id = int(row.get("id") or 0)
        row_user_id = int(row.get("user_id") or 0)
        url = str(row.get("url") or "")
        title = _short_admin_text(row.get("product_title") or url, 72)
        user_display = _user_display_html(
            row_user_id,
            row.get("username"),
            row.get("first_name"),
            row.get("last_name"),
        )
        fail_count = int(row.get("check_fail_count") or 0)
        last_error = _short_admin_text(row.get("last_check_error") or "-", 48)
        last_error_at = _format_dt(row.get("last_check_error_at"))
        last_price = _format_admin_price(row.get("last_price"))
        short_url = _short_admin_text(url, 110)

        block = (
            f"{index}. <code>{sub_id}</code> <b>{_safe_html(title)}</b>\n"
            f"   👤 {user_display} | fail: <b>{fail_count}</b> | last: {_safe_html(last_error_at)}\n"
            f"   💰 {_safe_html(last_price)} | reason: <code>{_safe_html(last_error)}</code>\n"
            f"   <code>{_safe_html(short_url)}</code>"
        )

        if len("\n\n".join(lines + [block])) > 3600:
            remaining = len(rows) - index + 1
            lines.append(f"...и еще {remaining} подписок.")
            break

        lines.append(block)
        if index <= 10:
            button_title = _short_admin_text(title, 22)
            keyboard_rows.append([
                InlineKeyboardButton(
                    text=f"{index}. #{sub_id} {button_title}",
                    callback_data=f"admin_bad_sub:{sub_id}",
                )
            ])

    keyboard_rows.extend([
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="admin_broken_subs")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="admin_main_menu")],
    ])
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
    await _edit_or_answer(
        message,
        "\n\n".join(lines),
        reply_markup=keyboard,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


def _get_broadcast_recipients() -> List[int]:
    with sqlite3.connect(DATABASE_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM users ORDER BY user_id")
        return [int(row[0]) for row in cursor.fetchall()]


async def _send_admin_broadcast(message: types.Message, text: str) -> Dict[str, int]:
    users = _get_broadcast_recipients()
    sent_count = 0
    failed_count = 0

    status_msg = await _edit_or_answer(
        message,
        f"📤 <b>Рассылка запущена</b>\n\nПолучателей: {len(users)}\nОтправлено: 0",
        parse_mode="HTML",
        reply_markup=None,
    )

    broadcast_text = f"📢 <b>Объявление</b>\n\n{_safe_html(text)}"

    for recipient_id in users:
        try:
            await _get_runtime_bot().send_message(recipient_id, broadcast_text, parse_mode="HTML")
            sent_count += 1

            if sent_count % 10 == 0:
                await status_msg.edit_text(
                    f"📤 <b>Рассылка идет</b>\n\n"
                    f"Отправлено: {sent_count}/{len(users)}\n"
                    f"Не доставлено: {failed_count}",
                    parse_mode="HTML",
                )

            await asyncio.sleep(0.1)

        except (TelegramForbiddenError, TelegramBadRequest) as e:
            logger.warning("Broadcast delivery failed to %s: %s", recipient_id, e)
            failed_count += 1
        except Exception as e:
            logger.warning("Unexpected broadcast error for %s: %s", recipient_id, e)
            failed_count += 1

    await status_msg.edit_text(
        f"✅ <b>Рассылка завершена</b>\n\n"
        f"📤 Отправлено: {sent_count}\n"
        f"❌ Не доставлено: {failed_count}",
        parse_mode="HTML",
    )
    return {"sent": sent_count, "failed": failed_count, "total": len(users)}


async def admin_broadcast(message: types.Message, text: str):
    """Prepare broadcast preview and require explicit confirmation."""
    try:
        admin_user_id = _get_request_user_id(message)
        if not is_admin(admin_user_id):
            await message.answer(t(admin_user_id, "admin_access_denied"))
            return

        text = (text or "").strip()
        if not text:
            await message.answer("❌ Укажите сообщение: <code>/admin broadcast текст</code>", parse_mode="HTML")
            return

        recipients_count = len(_get_broadcast_recipients())
        token = _store_admin_action(
            _PENDING_BROADCASTS,
            admin_user_id,
            {"text": text, "recipients_count": recipients_count},
        )
        action_event(
            "ADMIN",
            "prepared broadcast",
            admin=admin_user_id,
            recipients=recipients_count,
            text=short_value(text, 60),
        )

        await message.answer(
            "📢 <b>Предпросмотр рассылки</b>\n\n"
            f"Получателей: <b>{recipients_count}</b>\n\n"
            "Так пользователи увидят сообщение:\n\n"
            f"📢 <b>Объявление</b>\n\n{_safe_html(text)}\n\n"
            "Отправить всем пользователям?",
            reply_markup=_confirm_keyboard(
                f"admin_broadcast_confirm:{token}",
                f"admin_broadcast_cancel:{token}",
            ),
            parse_mode="HTML",
        )

    except Exception as e:
        logger.exception("Error in admin_broadcast: %s", e)
        await message.answer(f"❌ Ошибка при подготовке рассылки: {_safe_html(e)}", parse_mode="HTML")


async def admin_broadcast_confirm(message: types.Message, admin_user_id: int, token: str) -> None:
    payload = _pop_admin_action(_PENDING_BROADCASTS, token, admin_user_id)
    if not payload:
        await _edit_or_answer(
            message,
            "⚠️ Черновик рассылки устарел или уже был обработан.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🏠 Админ-панель", callback_data="admin_main_menu")]
            ]),
        )
        return

    action_event(
        "ADMIN",
        "confirmed broadcast",
        admin=admin_user_id,
        recipients=payload.get("recipients_count"),
        text=short_value(payload.get("text"), 60),
    )
    await _send_admin_broadcast(message, str(payload.get("text") or ""))


async def admin_broadcast_cancel(message: types.Message, admin_user_id: int, token: str) -> None:
    _pop_admin_action(_PENDING_BROADCASTS, token, admin_user_id)
    action_event("ADMIN", "cancelled broadcast", admin=admin_user_id)
    await _edit_or_answer(
        message,
        "🚫 Рассылка отменена.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏠 Админ-панель", callback_data="admin_main_menu")]
        ]),
    )


async def admin_users(message: types.Message):
    """Show list of active users or detailed info about specific user"""
    try:
        from database import get_connection


        args = message.text.split()
        target_user_id = None

        if len(args) > 2 and args[1] == "users" and args[2].isdigit():
            target_user_id = int(args[2])

        if target_user_id:

            action_event("ADMIN", "requested user details", admin=actor_label(message.from_user), target_user=target_user_id)
            await admin_user_details(message, target_user_id)
        else:

            action_event("ADMIN", "requested users list", admin=actor_label(message.from_user))
            await admin_users_list(message)

    except Exception as e:
        logger.exception("Error in admin_users: %s", e)
        await message.answer(f"❌ {t(message.from_user.id, 'error_generic')}: {e}")

async def admin_users_list(message: types.Message):
    """Show list of active users"""
    try:
        admin_user_id = _get_request_user_id(message)
        users_text, keyboard = _build_admin_users_page(admin_user_id, offset=0)
        await message.answer(users_text, reply_markup=keyboard, parse_mode="HTML")

    except Exception as e:
        logger.exception("Error in admin_users_list: %s", e)
        await message.answer(f"❌ {t(message.from_user.id, 'error_generic')}: {e}")

async def admin_users_list_interactive(message: types.Message, offset: int = 0):
    """Callback version of admin_users_list for refresh functionality"""
    try:
        admin_user_id = _get_request_user_id(message)
        users_text, keyboard = _build_admin_users_page(admin_user_id, offset=offset)

        try:
            await message.edit_text(users_text, reply_markup=keyboard, parse_mode="HTML")
        except Exception as e:
            if _is_message_not_modified_error(e):
                logger.debug("Admin users refresh skipped: message is already up to date")
                return


            if "BUTTON_USER_INVALID" in str(e):
                control_rows = [
                    [
                        InlineKeyboardButton(text="🔄 Обновить", callback_data=f"admin_users_refresh:{offset}"),
                        InlineKeyboardButton(text="🏠 Главное меню", callback_data="admin_main_menu"),
                    ]
                ]
                fallback_text = users_text + "\n\n💡 Для деталей: /admin users <id>"
                fallback_kb = InlineKeyboardMarkup(inline_keyboard=control_rows)
                try:
                    await message.edit_text(fallback_text, reply_markup=fallback_kb, parse_mode="HTML")
                except Exception as fallback_e:
                    if _is_message_not_modified_error(fallback_e):
                        logger.debug("Admin users fallback refresh skipped: message is already up to date")
                        return
                    raise
                return
            raise

    except Exception as e:
        logger.exception("Error in admin_users_list_callback: %s", e)
        try:
            await message.edit_text(f"❌ {t(admin_user_id, 'error_generic')}: {e}")
        except Exception as edit_error:
            if not _is_message_not_modified_error(edit_error):
                raise

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


            profile_exprs = _profile_select_exprs(column_names)

            if has_created_at:
                cursor.execute("""
                    SELECT
                        user_id,
                        language,
                        notify_quiet_hours_start,
                        notify_quiet_hours_end,
                        created_at,
                        {profile_exprs}
                    FROM users
                    WHERE user_id = ?
                """.format(profile_exprs=profile_exprs.replace("u.", "")), (target_user_id,))
            else:
                cursor.execute("""
                    SELECT
                        user_id,
                        language,
                        notify_quiet_hours_start,
                        notify_quiet_hours_end,
                        0 as created_at,
                        {profile_exprs}
                    FROM users
                    WHERE user_id = ?
                """.format(profile_exprs=profile_exprs.replace("u.", "")), (target_user_id,))

            user_data = cursor.fetchone()

            if not user_data:
                await message.answer(f"❌ {t(message.from_user.id, 'admin_user_not_found')}")
                return

            (
                user_id,
                language,
                quiet_start,
                quiet_end,
                created_at,
                username,
                first_name,
                last_name,
                telegram_language_code,
                is_premium,
                last_seen_at,
            ) = user_data


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

            user_text += _user_profile_block(
                first_name=first_name,
                last_name=last_name,
                username=username,
                telegram_language_code=telegram_language_code,
                is_premium=is_premium,
                last_seen_at=last_seen_at,
                source_label="сохранено в базе",
            )
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
                    title = _safe_html(title)
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


            profile_exprs = _profile_select_exprs(column_names)

            if has_created_at:
                cursor.execute("""
                    SELECT
                        user_id,
                        language,
                        notify_quiet_hours_start,
                        notify_quiet_hours_end,
                        created_at,
                        {profile_exprs}
                    FROM users
                    WHERE user_id = ?
                """.format(profile_exprs=profile_exprs.replace("u.", "")), (target_user_id,))
            else:
                cursor.execute("""
                    SELECT
                        user_id,
                        language,
                        notify_quiet_hours_start,
                        notify_quiet_hours_end,
                        0 as created_at,
                        {profile_exprs}
                    FROM users
                    WHERE user_id = ?
                """.format(profile_exprs=profile_exprs.replace("u.", "")), (target_user_id,))

            user_data = cursor.fetchone()

            if not user_data:
                await message.edit_text(f"❌ {t(admin_user_id, 'admin_user_not_found')}")
                return

            (
                user_id,
                language,
                quiet_start,
                quiet_end,
                created_at,
                username,
                first_name,
                last_name,
                telegram_language_code,
                is_premium,
                last_seen_at,
            ) = user_data


            telegram_user_info = _user_profile_block(
                first_name=first_name,
                last_name=last_name,
                username=username,
                telegram_language_code=telegram_language_code,
                is_premium=is_premium,
                last_seen_at=last_seen_at,
                source_label="сохранено в базе",
            )
            try:

                chat_member = await _get_runtime_bot().get_chat_member(chat_id=target_user_id, user_id=target_user_id)
                telegram_user = chat_member.user
                from database import save_user_profile

                save_user_profile(telegram_user)


                full_name = ""
                if telegram_user.first_name:
                    full_name = telegram_user.first_name
                if telegram_user.last_name:
                    full_name += f" {telegram_user.last_name}"
                full_name = full_name.strip() or "Неизвестно"


                username = f"@{telegram_user.username}" if telegram_user.username else "Не установлен"


                premium_status = "⭐ Да" if getattr(telegram_user, 'is_premium', False) else "Обычный"


                telegram_lang = getattr(telegram_user, 'language_code', 'Неизвестно')
                full_name = _safe_html(full_name)
                username = _safe_html(username)
                premium_status = _safe_html(premium_status)
                telegram_lang = _safe_html(telegram_lang)

                telegram_user_info = f"""
👨‍💼 <b>Имя:</b> {full_name}
📱 <b>Username:</b> {username}
🌐 <b>Язык Telegram:</b> {telegram_lang}
⭐ <b>Премиум:</b> {premium_status}
💾 <b>Источник профиля:</b> Telegram API"""

            except Exception as e:
                logger.warning(f"Could not get Telegram user info for {target_user_id}: {e}")
                telegram_user_info += "\n⚠️ <b>Telegram API сейчас не отдал профиль, показаны сохранённые данные.</b>"


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
                    title = _safe_html(title)
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

def _collect_cleanup_preview() -> Dict[str, int]:
    now = int(time.time())
    price_history_cutoff = now - 30 * 24 * 3600
    inactive_user_cutoff = now - 90 * 24 * 3600

    with sqlite3.connect(DATABASE_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM price_history WHERE ts < ?", (price_history_cutoff,))
        old_price_points = int(cursor.fetchone()[0])

        cursor.execute("""
            SELECT COUNT(*)
            FROM users
            WHERE user_id NOT IN (SELECT DISTINCT user_id FROM subscriptions)
            AND created_at < ?
        """, (inactive_user_cutoff,))
        inactive_users = int(cursor.fetchone()[0])

    return {
        "price_history_cutoff": price_history_cutoff,
        "inactive_user_cutoff": inactive_user_cutoff,
        "old_price_points": old_price_points,
        "inactive_users": inactive_users,
    }


def _execute_cleanup(preview: Dict[str, int]) -> Dict[str, int]:
    with sqlite3.connect(DATABASE_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM price_history WHERE ts < ?",
            (int(preview["price_history_cutoff"]),),
        )
        deleted_price_points = cursor.rowcount

        cursor.execute("""
            DELETE FROM users
            WHERE user_id NOT IN (SELECT DISTINCT user_id FROM subscriptions)
            AND created_at < ?
        """, (int(preview["inactive_user_cutoff"]),))
        deleted_users = cursor.rowcount

        cursor.execute("PRAGMA optimize")
        conn.commit()

    return {
        "deleted_price_points": max(0, deleted_price_points),
        "deleted_users": max(0, deleted_users),
    }


async def admin_cleanup(message: types.Message):
    """Prepare cleanup preview and require explicit confirmation."""
    try:
        admin_user_id = _get_request_user_id(message)
        if not is_admin(admin_user_id):
            await message.answer(t(admin_user_id, "admin_access_denied"))
            return

        preview = _collect_cleanup_preview()
        token = _store_admin_action(_PENDING_CLEANUPS, admin_user_id, preview)
        action_event(
            "ADMIN",
            "prepared cleanup",
            admin=admin_user_id,
            old_price_points=preview["old_price_points"],
            inactive_users=preview["inactive_users"],
        )

        await message.answer(
            "🧹 <b>Предпросмотр очистки</b>\n\n"
            "Будет создан бэкап базы, и только после этого я удалю:\n"
            f"• старые точки истории цен старше 30 дней: <b>{preview['old_price_points']}</b>\n"
            f"• пользователей без подписок старше 90 дней: <b>{preview['inactive_users']}</b>\n\n"
            "Подтвердить очистку?",
            reply_markup=_confirm_keyboard(
                f"admin_cleanup_confirm:{token}",
                f"admin_cleanup_cancel:{token}",
            ),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.exception("Error preparing admin cleanup: %s", e)
        await message.answer(f"❌ Ошибка при подготовке очистки: {_safe_html(e)}", parse_mode="HTML")


async def admin_cleanup_confirm(message: types.Message, admin_user_id: int, token: str) -> None:
    preview = _pop_admin_action(_PENDING_CLEANUPS, token, admin_user_id)
    if not preview:
        await _edit_or_answer(
            message,
            "⚠️ Запрос на очистку устарел или уже был обработан.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🏠 Админ-панель", callback_data="admin_main_menu")]
            ]),
        )
        return

    try:
        action_event(
            "ADMIN",
            "confirmed cleanup",
            admin=admin_user_id,
            old_price_points=preview["old_price_points"],
            inactive_users=preview["inactive_users"],
        )
        await _edit_or_answer(
            message,
            "💾 <b>Создаю бэкап перед очисткой...</b>",
            parse_mode="HTML",
            reply_markup=None,
        )
        backup = await _create_database_backup(trigger="cleanup")
        deleted = _execute_cleanup(preview)
        action_event(
            "ADMIN",
            "cleanup finished",
            admin=admin_user_id,
            deleted_price_points=deleted["deleted_price_points"],
            deleted_users=deleted["deleted_users"],
        )

        await _edit_or_answer(
            message,
            "✅ <b>Очистка завершена</b>\n\n"
            f"💾 Бэкап: <code>{_safe_html(backup['path'])}</code>\n"
            f"📊 Размер бэкапа: {backup['size_mb']:.1f} MB\n\n"
            "Удалено:\n"
            f"• старых точек истории цен: <b>{deleted['deleted_price_points']}</b>\n"
            f"• неактивных пользователей: <b>{deleted['deleted_users']}</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🏠 Админ-панель", callback_data="admin_main_menu")]
            ]),
        )
    except Exception as e:
        logger.exception("Error executing admin cleanup: %s", e)
        await _edit_or_answer(
            message,
            f"❌ Очистка не выполнена: {_safe_html(e)}",
            parse_mode="HTML",
        )


async def admin_cleanup_cancel(message: types.Message, admin_user_id: int, token: str) -> None:
    _pop_admin_action(_PENDING_CLEANUPS, token, admin_user_id)
    action_event("ADMIN", "cancelled cleanup", admin=admin_user_id)
    await _edit_or_answer(
        message,
        "🚫 Очистка отменена. Данные не менялись.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏠 Админ-панель", callback_data="admin_main_menu")]
        ]),
    )


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
    backups_dir = Path(BACKUP_DIR)
    backups_dir.mkdir(parents=True, exist_ok=True)

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
    action_event("BACKUP", "database backup created", trigger=trigger, size_mb=f"{size_mb:.1f}", retained=retained)
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

            full_name = _safe_html(full_name)
            username = _safe_html(username)
            telegram_lang = _safe_html(telegram_lang)
            premium_status = _safe_html(premium_status)
            created_date = _safe_html(created_date)

            user_info = f"""
👨‍💼 <b>Имя:</b> {full_name}
📱 <b>Username:</b> {username}
🌐 <b>Язык Telegram:</b> {telegram_lang}
⭐ <b>Премиум:</b> {premium_status}
📅 <b>Регистрация:</b> {created_date}"""


        safe_report_text = _safe_html(report_text)
        admin_report = f"""
📋 <b>НОВЫЙ РЕПОРТ ОТ ПОЛЬЗОВАТЕЛЯ</b>

👤 <b>ID:</b> <code>{user_id}</code>
🌐 <b>Язык бота:</b> {user_lang}
📊 <b>Подписок:</b> {subs_count}{user_info}

💬 <b>Сообщение:</b>
{safe_report_text}

<i>Используйте /admin respond {user_id} [текст ответа] для ответа</i>
"""


        if not ADMIN_IDS:
            raise ReportDeliveryError("No admin recipients configured")

        try:
            runtime_bot = _get_runtime_bot()
        except Exception as exc:
            raise ReportDeliveryError("Bot runtime is unavailable") from exc

        sent_count = 0
        failed_count = 0
        for admin_id in ADMIN_IDS:
            try:
                await runtime_bot.send_message(admin_id, admin_report, parse_mode="HTML")
                sent_count += 1
            except (TelegramForbiddenError, TelegramBadRequest) as e:
                failed_count += 1
                logger.warning("Failed to send report to admin %s: %s", admin_id, e)
            except Exception as e:
                failed_count += 1
                logger.warning("Failed to send report to admin %s: %s", admin_id, e)

        if sent_count == 0:
            action_event(
                "USER",
                "report delivery failed",
                user=user_id,
                admins=len(ADMIN_IDS),
                chars=len(report_text or ""),
            )
            raise ReportDeliveryError("Report delivery failed for all admins")

        action_event(
            "USER",
            "sent report to admins",
            user=user_id,
            admins=sent_count,
            failed_admins=failed_count,
            chars=len(report_text or ""),
        )

        if message:
            await message.answer(t(user_id, "report_sent"), parse_mode="HTML")

    except Exception as e:
        logger.exception("Error submitting user report: %s", e)
        if message and hasattr(message, 'answer'):
            try:
                error_key = "report_delivery_failed" if isinstance(e, ReportDeliveryError) else "error_generic"
                await message.answer(t(user_id, error_key))
            except Exception:
                pass

async def admin_respond(message: types.Message):
    """Admin command to respond to user reports"""
    try:
        if message.from_user.id not in ADMIN_IDS:
            await message.answer("❌ У вас нет прав администратора")
            return

        parts = (message.text or "").split(maxsplit=3)
        if len(parts) < 4:
            await message.answer("❌ Использование: <code>/admin respond user_id текст ответа</code>", parse_mode="HTML")
            return

        target_user_id = int(parts[2])
        response_text = parts[3].strip()
        if not response_text:
            await message.answer("❌ Текст ответа не может быть пустым.")
            return


        try:
            response_message = (
                "💬 <b>Ответ администратора</b>\n\n"
                f"{_safe_html(response_text)}\n\n"
                "<i>Если у вас есть дополнительные вопросы, используйте /report.</i>"
            )
            await _get_runtime_bot().send_message(target_user_id, response_message, parse_mode="HTML")
            action_event(
                "ADMIN",
                "responded to user report",
                admin=actor_label(message.from_user),
                target_user=target_user_id,
                chars=len(response_text),
            )


            await message.answer(f"✅ Ответ отправлен пользователю <code>{target_user_id}</code>", parse_mode="HTML")

        except Exception as e:
            logger.warning(f"Failed to send response to user {target_user_id}: {e}")
            await message.answer(f"❌ Не удалось отправить ответ пользователю <code>{target_user_id}</code>", parse_mode="HTML")

    except ValueError:
        await message.answer("❌ Неверный формат user_id")
    except Exception as e:
        logger.exception("Error in admin_respond: %s", e)
        await message.answer(f"❌ Ошибка: {_safe_html(e)}", parse_mode="HTML")

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
            if not url.lower().startswith(("http://", "https://")):
                await message.answer("❌ Ссылка должна начинаться с http:// или https://")
                return

            if add_recommended_product(title, url, price, category, brand, reason):

                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="📋 Посмотреть список", callback_data="admin_recommend_list")]
                ])
                await message.answer(
                    f"✅ <b>Продукт успешно добавлен!</b>\n\n"
                    f"📦 <b>{_safe_html(title)}</b>\n"
                    f"💰 {_safe_html(price or 'Цена не указана')}\n"
                    f"🎯 {_safe_html(category or 'Категория не указана')}\n"
                    f"🏷️ {_safe_html(brand or 'Бренд не указан')}",
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
        safe_title = _safe_html(str(product.get('title') or '')[:30])
        safe_price = _safe_html(product.get('price') or '—')
        safe_category = _safe_html(product.get('category') or '—')
        response += f"{i}. {priority_stars} <b>{safe_title}</b>\n"
        response += f"   💰 {safe_price} | 🎯 {safe_category}\n"


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

                await _get_runtime_bot().send_chat_action(chat_id=user_id, action="typing")
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

class AdminHandler(BaseHandler):
    """Register admin command handlers."""

    def register(self, dp):
        dp.message.register(cmd_admin, Command("admin"))
        dp.message.register(admin_broken_subscriptions, Command("bad_subs"))
