"""
Handlers for subscription-related commands and functionality.
"""
from typing import List, Tuple
from aiogram import types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.types import InlineKeyboardButton

from .base import BaseHandler
from database import (
    get_user_subscriptions, get_subscription, remove_subscription,
    add_user_if_not_exists, add_subscription, update_last_price,
    update_subscription_meta
)
from config import DEFAULT_NOTIFY_MODE
from scraper import get_product_info_async, get_price_history_from_akakce_async
from services.notification_service import NotificationService
from keyboards import subscription_controls_kb_for_user
import bot
from bot import normalize_url, is_trendyol_product_url, resolve_short_url, send_history_plot
from utils import get_next_notification_time
import logging


class SubscriptionHandler(BaseHandler):
    """Handler for subscription management commands."""

    def __init__(self):
        super().__init__()
        self.notification_service = NotificationService(self.bot)

    async def handle_mysubs_command(self, message: types.Message):
        """Handle /mysubs command."""
        await self._show_user_subscriptions(message)

    async def handle_unsubscribe_command(self, message: types.Message):
        """Handle /unsubscribe command."""
        parts = (message.text or "").split()
        if len(parts) < 2 or not parts[1].isdigit():
            await message.answer(self.t(message.from_user.id, "provide_subscription_id"))
            return

        sid = int(parts[1])
        sub = get_subscription(sid)
        if not sub or sub[1] != message.from_user.id:
            await message.answer(self.t(message.from_user.id, "no_subs"))
            return

        try:
            remove_subscription(sid)
            await message.answer(self.t(message.from_user.id, "sub_removed"))
        except Exception:
            await message.answer(self.t(message.from_user.id, "error_generic"))

    async def handle_url_subscription(self, message: types.Message):
        """Handle Trendyol URL subscription."""
        try:
            raw = (message.text or "").strip()
            url = await resolve_short_url(raw)
            url = normalize_url(url)
            url_lower = url.lower()

            if "trendyol.com" not in url_lower and "ty.gl/" not in url_lower:
                await message.answer(self.t(message.from_user.id, "not_trendyol"))
                return

            if not is_trendyol_product_url(url):
                await message.answer(self.t(message.from_user.id, "not_product_url"))
                return

            add_user_if_not_exists(message.from_user.id)

            # Check for duplicates
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
                    await message.answer(self.t(message.from_user.id, "already_subscribed"))
                    return

            # Create subscription
            sub_id = add_subscription(message.from_user.id, url, DEFAULT_NOTIFY_MODE)

            # Get product info
            try:
                price, title, image = await get_product_info_async(url)
            except Exception as e:
                logging.getLogger(__name__).warning("Error fetching product info: %s", e)
                price, title, image = None, None, None

            # Update subscription metadata
            try:
                if title or image:
                    update_subscription_meta(sub_id, title, image)
            except Exception as e:
                logging.getLogger(__name__).warning("Error updating subscription meta: %s", e)

            # Send confirmation message with friendlier styling
            controls = subscription_controls_kb_for_user(message.from_user.id, sub_id)
            if price is not None:
                try:
                    update_last_price(sub_id, price)
                    text = self.t(message.from_user.id, "subscribed_now").format(price=price)
                    if title:
                        header = f"*{title}*\n\n"
                        text = header + text

                    # Use Markdown and emojis for nicer look
                    try:
                        if image:
                            # Use centralized NotificationService to send photo with fallback
                            await bot.notification_service.send_notification_safe(
                                message.from_user.id,
                                text,
                                image=image,
                                parse_mode="Markdown",
                            )
                            # edit: still include keyboard by sending a separate message with controls
                            try:
                                await message.answer("", reply_markup=controls)
                            except Exception:
                                pass
                        else:
                            await message.answer(text, reply_markup=controls, parse_mode="Markdown")
                    except Exception:
                        await message.answer(text, reply_markup=controls, parse_mode="Markdown")
                except Exception as e:
                    logging.getLogger(__name__).exception("Error sending subscription confirmation: %s", e)
                    await message.answer(self.t(message.from_user.id, "subscribed"), reply_markup=controls)
            else:
                text = self.t(message.from_user.id, "subscribed_no_price")
                if title:
                    text = f"*{title}*\n\n" + text
                await message.answer(text, reply_markup=controls, parse_mode="Markdown")

        except Exception as e:
            logging.getLogger(__name__).exception("Error in handle_url_subscription: %s", e)
            await message.answer(self.t(message.from_user.id, "error_generic"))

    async def _show_user_subscriptions(self, message: types.Message):
        """Show user's subscriptions."""
        user_id = message.from_user.id
        subs = get_user_subscriptions(user_id)

        if not subs:
            await message.answer(self.t(user_id, "no_subs"))
            return

        # Формируем одно сообщение со списком всех подписок
        lines = [self.t(user_id, "mysubs_header")]
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
            status_text = self.t(user_id, "status_active") if last_price is not None else self.t(user_id, "status_inactive")

            # Форматируем цену
            price_text = f"{last_price:.0f} TL" if last_price is not None else self.t(user_id, "unknown_price")

            # Форматируем режим и время следующего уведомления
            mode_text = self.t(user_id, "mode_hourly") if mode == "hourly" else self.t(user_id, "mode_discount")
            next_notify = get_next_notification_time(mode, last_notify_time, notify_interval, user_id, self.t)

            # Используем название товара или URL
            title = product_title if product_title else url[:50] + "..." if len(url) > 50 else url

            # Формируем строку для подписки
            sub_line = f"\n{status_icon} *{status_text}* | ID: `{sub_id}`\n"
            sub_line += f"📦 {title}\n"
            sub_line += f"💰 {price_text} | 🔔 {next_notify}\n"

            # Добавляем информацию о целевой цене, если установлена
            if price_alert is not None:
                sub_line += f"🎯 {self.t(user_id, 'price_alert_label')}: {price_alert:.0f} TL\n"

            lines.append(sub_line)

            # Добавляем кнопку для редактирования этой подписки
            inline_buttons.append([
                InlineKeyboardButton(
                    text=f"⚙️ {self.t(user_id, 'btn_edit')} ID {sub_id}",
                    callback_data=f"edit_sub:{sub_id}"
                )
            ])

        # Разбиваем на части если слишком длинное сообщение
        full_text = "\n".join(lines)
        if len(full_text) > 4000:  # Telegram limit
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
            # Fallback без клавиатуры если что-то пошло не так
            print(f"Error sending keyboard: {e}")
            await message.answer(full_text, parse_mode="Markdown")

    def register(self, dp):
        """Register all subscription-related handlers."""
        from aiogram import F
        from aiogram.filters import Command
        
        # Commands
        dp.message.register(self.handle_mysubs_command, Command("mysubs"))
        dp.message.register(self.handle_unsubscribe_command, Command("unsubscribe"))

        # URL subscription handler
        dp.message.register(
            self.handle_url_subscription,
            F.text.contains("trendyol.com") | F.text.contains("ty.gl/")
        )
