"""Admin commands, admin callbacks, and maintenance helpers."""
import asyncio
import html
import logging
import os
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from aiogram import types
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from analytics import Analytics
from config import ADMIN_IDS, DATABASE_PATH
from database import (
    create_sqlite_backup,
    get_bot_text,
    get_user_language,
    get_user_subscriptions,
    set_bot_text,
)
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


def _get_runtime_bot():
    from bot import bot as runtime_bot

    return runtime_bot

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
                await _get_runtime_bot().send_message(user_id, f"📢 <b>ОБЪЯВЛЕНИЕ</b>\n\n{text}", parse_mode="HTML")
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

                chat_member = await _get_runtime_bot().get_chat_member(chat_id=target_user_id, user_id=target_user_id)
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
                await _get_runtime_bot().send_message(admin_id, admin_report, parse_mode="HTML")
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
            await _get_runtime_bot().send_message(target_user_id, response_message, parse_mode="HTML")


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