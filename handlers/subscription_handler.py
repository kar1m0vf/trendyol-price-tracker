"""
Handlers for subscription-related commands and functionality.
"""
from aiogram import types
from aiogram.filters import Command

from .base import BaseHandler
from database import (
    get_user_subscriptions, remove_subscription,
    add_user_if_not_exists, add_subscription, update_last_price,
    update_subscription_meta
)
from config import DEFAULT_NOTIFY_MODE
from scraper import get_product_info_async
from keyboards import subscription_controls_kb_for_user
import logging


class SubscriptionHandler(BaseHandler):
    """Handler for subscription management commands."""

    def __init__(self):
        super().__init__()

    async def handle_mysubs_command(self, message: types.Message):
        """Handle /mysubs command."""
        await self._show_user_subscriptions(message)

    async def handle_unsubscribe_command(self, message: types.Message):
        """Handle /unsubscribe command."""
        from bot import resolve_user_subscription_ref

        parts = (message.text or "").split()
        if len(parts) < 2 or not parts[1].isdigit():
            await message.answer(self.t(message.from_user.id, "provide_subscription_id"))
            return

        sub, _public_number = resolve_user_subscription_ref(message.from_user.id, parts[1])
        if not sub:
            await message.answer(self.t(message.from_user.id, "no_subs"))
            return
        sid = sub[0]

        try:
            remove_subscription(sid)
            await message.answer(self.t(message.from_user.id, "sub_removed"))
        except Exception:
            await message.answer(self.t(message.from_user.id, "error_generic"))

    async def handle_url_subscription(self, message: types.Message):
        """Handle Trendyol URL subscription."""
        from bot import (
            normalize_url,
            is_trendyol_product_url,
            resolve_short_url,
            send_subscription_added_message,
        )

        user_id = message.from_user.id
        status_message = None
        try:
            raw = (message.text or "").strip()
            url = await resolve_short_url(raw)
            url = normalize_url(url)
            url_lower = url.lower()

            if "trendyol.com" not in url_lower and "ty.gl/" not in url_lower:
                await message.answer(self.t(user_id, "not_trendyol"))
                return

            if not is_trendyol_product_url(url):
                await message.answer(self.t(user_id, "not_product_url"))
                return

            add_user_if_not_exists(user_id)

                                  
            subs = get_user_subscriptions(user_id)
            for sub in subs:
                try:
                    (sid, _sub_user_id, u, mode, last_price, product_title, product_image,
                     min_price, max_price, notify_percent, notify_interval, last_notify_time, price_alert) = sub
                except ValueError:

                    (sid, _sub_user_id, u, mode, last_price, product_title, product_image,
                     min_price, max_price, notify_percent, notify_interval, last_notify_time) = sub[:12]

                if normalize_url(u).lower() == url_lower:
                    await message.answer(self.t(user_id, "already_subscribed"))
                    return

            status_message = await self.send_status_message(
                message,
                self.t(user_id, "status_checking_product"),
            )


            sub_id = add_subscription(user_id, url, DEFAULT_NOTIFY_MODE)

                              
            try:
                price, title, image = await get_product_info_async(url)
            except Exception as e:
                logging.getLogger(__name__).warning("Error fetching product info: %s", e)
                price, title, image = None, None, None

                                          
            try:
                if title or image:
                    update_subscription_meta(sub_id, title, image)
            except Exception as e:
                logging.getLogger(__name__).warning("Error updating subscription meta: %s", e)

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
                except Exception as e:
                    logging.getLogger(__name__).exception("Error sending subscription confirmation: %s", e)
                    await message.answer(
                        self.t(user_id, "subscribed"),
                        reply_markup=subscription_controls_kb_for_user(user_id, sub_id),
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
            await self.clear_status_message(status_message)

        except Exception as e:
            logging.getLogger(__name__).exception("Error in handle_url_subscription: %s", e)
            if status_message is not None:
                await self.replace_status_message(status_message, self.t(user_id, "error_generic"), fallback_target=message)
            else:
                await message.answer(self.t(user_id, "error_generic"))

    async def _show_user_subscriptions(self, message: types.Message):
        """Show user's subscriptions."""
        from bot import build_subscriptions_overview

        user_id = message.from_user.id
        subs = get_user_subscriptions(user_id)

        if not subs:
            await message.answer(self.t(user_id, "no_subs"))
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
            logging.getLogger(__name__).exception("Error sending subscriptions overview: %s", e)
            await message.answer(self.t(user_id, "error_generic"))

    def register(self, dp):
        """Register all subscription-related handlers."""
        from aiogram import F
        from aiogram.filters import Command
        
                  
        dp.message.register(self.handle_mysubs_command, Command("mysubs"))
        dp.message.register(self.handle_unsubscribe_command, Command("unsubscribe"))

                                  
        dp.message.register(
            self.handle_url_subscription,
            F.text.contains("trendyol.com") | F.text.contains("ty.gl/")
        )
