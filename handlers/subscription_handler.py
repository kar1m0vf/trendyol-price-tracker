"""
Handlers for subscription-related commands and functionality.
"""
from aiogram import types
from aiogram.filters import Command

from .base import BaseHandler
from database import (
    get_user_subscriptions, remove_subscription,
    add_user_if_not_exists, add_subscription, update_last_price,
    update_subscription_meta, save_user_profile
)
from config import DEFAULT_NOTIFY_MODE
from localization import LOCALES
from logging_utils import action_event, actor_label, short_value
from scraper import get_product_info_async
from keyboards import get_main_kb, subscription_controls_kb_for_user
import logging


class SubscriptionHandler(BaseHandler):
    """Handler for subscription management commands."""

    def __init__(self):
        super().__init__()

    async def handle_mysubs_command(self, message: types.Message):
        """Handle /mysubs command."""
        action_event("USER", "requested subscriptions", user=actor_label(message.from_user))
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
            action_event("USER", "removed subscription", user=actor_label(message.from_user), sub_id=sid)
            await message.answer(self.t(message.from_user.id, "sub_removed"))
        except Exception:
            await message.answer(self.t(message.from_user.id, "error_generic"))

    async def _is_subscribe_button(self, message: types.Message) -> bool:
        if not message.text or not message.from_user:
            return False
        try:
            text = message.text.strip()
            return any(locale.get("btn_subscribe") == text for locale in LOCALES.values())
        except Exception as exc:
            logging.getLogger(__name__).exception("Subscribe button check failed: %s", exc)
            return False

    async def _is_supported_product_link_text(self, message: types.Message) -> bool:
        if not message.text or not message.from_user:
            return False
        try:
            from bot import extract_supported_url, is_trendyol_short_url

            candidate = extract_supported_url(message.text)
            candidate_lower = candidate.lower()
            return "trendyol.com" in candidate_lower or is_trendyol_short_url(candidate)
        except Exception as exc:
            logging.getLogger(__name__).exception("Product link check failed: %s", exc)
            return False

    async def handle_subscribe_button(self, message: types.Message):
        """Guide the user to send a product link."""
        action_event("USER", "opened add product prompt", user=actor_label(message.from_user))
        await message.answer(
            self.t(message.from_user.id, "send_link_prompt"),
            reply_markup=get_main_kb(message.from_user.id),
        )

    async def handle_url_subscription(self, message: types.Message):
        """Handle Trendyol URL subscription."""
        from bot import (
            extract_supported_url,
            normalize_url,
            is_trendyol_product_url,
            is_trendyol_short_url,
            resolve_short_url,
            send_subscription_added_message,
        )

        user_id = message.from_user.id
        status_message = None
        try:
            raw = extract_supported_url(message.text or "")
            url = await resolve_short_url(raw)
            url = normalize_url(url)
            url_lower = url.lower()

            if is_trendyol_short_url(url):
                await message.answer(self.t(user_id, "short_url_resolve_failed"))
                return

            if "trendyol.com" not in url_lower:
                await message.answer(self.t(user_id, "not_trendyol"))
                return

            if not is_trendyol_product_url(url):
                await message.answer(self.t(user_id, "not_product_url"))
                return

            add_user_if_not_exists(user_id)
            save_user_profile(message.from_user)
            try:
                from services.trending_service import TREND_SEARCH_AWAIT

                TREND_SEARCH_AWAIT.discard(user_id)
            except Exception:
                logging.getLogger(__name__).debug("Could not clear trending search state", exc_info=True)
            action_event("USER", "started adding product", user=actor_label(message.from_user))

            subs = get_user_subscriptions(user_id)
            for sub in subs:
                try:
                    (sid, _sub_user_id, u, mode, last_price, product_title, product_image,
                     min_price, max_price, notify_percent, notify_interval, last_notify_time, price_alert) = sub
                except ValueError:

                    (sid, _sub_user_id, u, mode, last_price, product_title, product_image,
                     min_price, max_price, notify_percent, notify_interval, last_notify_time) = sub[:12]

                if normalize_url(u).lower() == url_lower:
                    action_event("USER", "tried duplicate subscription", user=actor_label(message.from_user), sub_id=sid)
                    await message.answer(self.t(user_id, "already_subscribed"))
                    return

            status_message = await self.send_status_message(
                message,
                self.t(user_id, "status_checking_product"),
            )


            sub_id = add_subscription(user_id, url, DEFAULT_NOTIFY_MODE)
            action_event("USER", "subscription created", user=actor_label(message.from_user), sub_id=sub_id)

                              
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
                    action_event(
                        "USER",
                        "product price loaded",
                        user=actor_label(message.from_user),
                        sub_id=sub_id,
                        price=f"{price:.0f} TL",
                        title=short_value(title or "unknown"),
                    )
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
                action_event(
                    "USER",
                    "product added without price",
                    user=actor_label(message.from_user),
                    sub_id=sub_id,
                    title=short_value(title or "unknown"),
                )
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
        from aiogram.filters import Command
        
                  
        dp.message.register(self.handle_mysubs_command, Command("mysubs"))
        dp.message.register(self.handle_unsubscribe_command, Command("unsubscribe"))
        dp.message.register(self.handle_subscribe_button, self._is_subscribe_button)

                                  
        dp.message.register(
            self.handle_url_subscription,
            self._is_supported_product_link_text,
        )
