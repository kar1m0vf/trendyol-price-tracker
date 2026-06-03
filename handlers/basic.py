"""Basic handlers for start/help/language commands."""

import logging
from datetime import datetime

from aiogram import types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from access_control import get_effective_user_access, get_subscription_limit_for_user
from config import MAX_SUBSCRIPTIONS_PER_USER, PREMIUM_MAX_SUBSCRIPTIONS_PER_USER
from database import (
    add_user_if_not_exists,
    delete_user_data,
    get_user_profile,
    get_user_subscriptions,
    save_user_profile,
    set_user_language,
)
from keyboards import (
    get_fallback_inline_kb,
    get_help_inline_kb,
    get_main_kb,
    get_onboarding_inline_kb,
    get_premium_inline_kb,
)
from logging_utils import action_event, actor_label
from localization import LOCALES, clear_language_cache, update_language_cache
from user_texts import format_start_text
from .base import BaseHandler

logger = logging.getLogger(__name__)


def _format_access_date(ts: int) -> str:
    """Return a compact date for user-facing premium expiry text."""
    return datetime.fromtimestamp(int(ts)).strftime("%d.%m.%Y")


class BasicHandler(BaseHandler):
    """Handler for basic bot commands."""

    async def handle_start(self, message: types.Message):
        """Handle /start command."""
        user_id = message.from_user.id
        try:
            existing_profile = get_user_profile(user_id)
        except Exception as exc:
            logger.exception("Failed to load user profile before /start: %s", exc)
            existing_profile = None

        is_new_user = existing_profile is None
        add_user_if_not_exists(user_id)
        save_user_profile(message.from_user)
        action_event("USER", "opened /start", user=actor_label(message.from_user))

        try:
            lang_code = (message.from_user.language_code or "").split("-")[0].lower()
        except Exception as exc:
            logger.debug("Could not determine user language_code: %s", exc)
            lang_code = ""

        preferred = lang_code if lang_code in LOCALES else "en"

        if is_new_user:
            try:
                set_user_language(user_id, preferred)
                update_language_cache(user_id, preferred)
            except Exception as exc:
                logger.exception("Failed to set user language: %s", exc)
        else:
            existing_language = (existing_profile or {}).get("language")
            if existing_language in LOCALES:
                update_language_cache(user_id, existing_language)

        await message.answer(
            format_start_text(user_id, message.from_user, self.t),
            reply_markup=get_main_kb(user_id),
            parse_mode="Markdown",
        )
        if is_new_user:
            await message.answer(
                self.t(user_id, "onboarding_quick_actions"),
                reply_markup=get_onboarding_inline_kb(user_id),
            )

    async def handle_help(self, message: types.Message):
        """Handle /help command."""
        user_id = message.from_user.id
        args = (message.text or "").split(maxsplit=1)
        if len(args) > 1 and args[1].strip().lower() == "full":
            await message.answer(self.t(user_id, "help_full"))
            return

        await message.answer(
            self.t(user_id, "help_text"),
            reply_markup=get_help_inline_kb(user_id),
        )

    async def handle_terms(self, message: types.Message):
        """Show user-facing terms of use."""
        user_id = message.from_user.id
        await message.answer(
            self.t(user_id, "terms_text"),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

    async def handle_privacy(self, message: types.Message):
        """Show user-facing privacy information."""
        user_id = message.from_user.id
        await message.answer(
            self.t(user_id, "privacy_text"),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

    async def handle_support(self, message: types.Message):
        """Show support instructions."""
        user_id = message.from_user.id
        await message.answer(
            self.t(user_id, "support_text"),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

    async def handle_premium(self, message: types.Message):
        """Show the user's current internal premium status and limits."""
        user_id = message.from_user.id

        try:
            access = get_effective_user_access(user_id)
            limit = get_subscription_limit_for_user(user_id)
            current_count = len(get_user_subscriptions(user_id))
        except Exception as exc:
            logger.exception("Failed to build premium status for user=%s: %s", user_id, exc)
            await message.answer(self.t(user_id, "error_generic"))
            return

        has_premium_capacity = access["is_premium"] or limit is None

        if limit is None:
            status = self.t(user_id, "premium_status_admin")
            next_step = self.t(user_id, "premium_next_step_admin")
        elif access["is_premium"]:
            if access["premium_until"]:
                status = self.t(
                    user_id,
                    "premium_status_active_until",
                    date=_format_access_date(access["premium_until"]),
                )
            else:
                status = self.t(user_id, "premium_status_active_forever")
            next_step = self.t(user_id, "premium_next_step_active")
        elif access["is_expired"]:
            status = self.t(
                user_id,
                "premium_status_expired",
                date=_format_access_date(access["premium_until"]),
            )
            next_step = self.t(user_id, "premium_next_step_request")
        else:
            status = self.t(user_id, "premium_status_free")
            next_step = self.t(user_id, "premium_next_step_request")

        if limit is None:
            usage = self.t(user_id, "premium_usage_unlimited", count=current_count)
        else:
            usage = self.t(user_id, "premium_usage_limited", count=current_count, limit=limit)

        await message.answer(
            self.t(
                user_id,
                "premium_text",
                status=status,
                usage=usage,
                free_limit=MAX_SUBSCRIPTIONS_PER_USER,
                premium_limit=PREMIUM_MAX_SUBSCRIPTIONS_PER_USER,
                next_step=next_step,
            ),
            reply_markup=get_premium_inline_kb(user_id, is_premium=has_premium_capacity),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

    async def handle_delete_me(self, message: types.Message):
        """Delete user-owned bot data after explicit confirmation."""
        user_id = message.from_user.id
        args = (message.text or "").split(maxsplit=1)
        confirmed = len(args) > 1 and args[1].strip().lower() == "confirm"
        if not confirmed:
            await message.answer(
                self.t(user_id, "delete_me_confirm_text"),
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            return

        done_template = self.t(user_id, "delete_me_done")
        try:
            deleted = delete_user_data(user_id)
        except Exception as exc:
            logger.exception("Failed to delete user data for user=%s: %s", user_id, exc)
            await message.answer(self.t(user_id, "error_generic"))
            return

        clear_language_cache(user_id)
        action_event(
            "USER",
            "deleted own bot data",
            user=actor_label(message.from_user),
            subscriptions=deleted.get("subscriptions", 0),
            price_history=deleted.get("price_history", 0),
        )
        await message.answer(
            done_template.format(
                subscriptions=deleted.get("subscriptions", 0),
                price_history=deleted.get("price_history", 0),
            ),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

    async def handle_language_command(self, message: types.Message):
        """Handle /language command."""
        user_id = message.from_user.id
        parts = (message.text or "").split()
        if len(parts) > 1:
            code = parts[1].lower()
            if code in {"ru", "en", "az", "tr"}:
                set_user_language(user_id, code)
                update_language_cache(user_id, code)
                action_event("USER", "changed language", user=actor_label(message.from_user), language=code)
                try:
                    await message.answer(self.t(user_id, "lang_changed"))
                except Exception as exc:
                    logger.exception("Failed to send lang_changed message: %s", exc)
                try:
                    await self.bot.send_message(
                        user_id,
                        format_start_text(user_id, message.from_user, self.t),
                        reply_markup=get_main_kb(user_id),
                        parse_mode="Markdown",
                    )
                except Exception as exc:
                    logger.exception(
                        "Failed to send start_text after language change: %s", exc
                    )
            else:
                await message.answer(self.t(user_id, "invalid_language"))
        else:
            await self.handle_language_menu(message)

    async def handle_language_menu(self, message: types.Message):
        """Show language selection menu."""
        user_id = message.from_user.id
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=self.t(user_id, "lang_ru"), callback_data="lang:ru"
                    ),
                    InlineKeyboardButton(
                        text=self.t(user_id, "lang_en"), callback_data="lang:en"
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text=self.t(user_id, "lang_az"), callback_data="lang:az"
                    ),
                    InlineKeyboardButton(
                        text=self.t(user_id, "lang_tr"), callback_data="lang:tr"
                    ),
                ],
            ]
        )
        await message.answer(self.t(user_id, "choose_language"), reply_markup=kb)

    async def handle_language_button(self, message: types.Message):
        """Handle language button press."""
        await self.handle_language_menu(message)

    async def handle_help_button(self, message: types.Message):
        """Handle help button press."""
        await self.handle_help(message)

    async def handle_premium_button(self, message: types.Message):
        """Handle premium button press."""
        await self.handle_premium(message)

    async def handle_ping_text(self, message: types.Message):
        """Answer to a plain text ping."""
        user_id = message.from_user.id
        await message.answer(self.t(user_id, "ping_pong"))

    async def handle_unrecognized_text(self, message: types.Message):
        """Guide users when a plain text message did not match any workflow."""
        user_id = message.from_user.id
        await message.answer(
            self.t(user_id, "fallback_text"),
            reply_markup=get_fallback_inline_kb(user_id),
        )

    def register(self, dp):
        """Register all handlers."""
        dp.message.register(self.handle_start, Command("start"))
        dp.message.register(self.handle_help, Command("help"))
        dp.message.register(self.handle_terms, Command("terms"))
        dp.message.register(self.handle_privacy, Command("privacy"))
        dp.message.register(self.handle_support, Command("support"))
        dp.message.register(self.handle_premium, Command("premium"))
        dp.message.register(self.handle_delete_me, Command("delete_me"))
        dp.message.register(self.handle_language_command, Command("language"))

        async def is_language_button(message):
            if not message.text:
                return False
            try:
                return any(
                    locale.get("btn_language") == message.text
                    for locale in LOCALES.values()
                )
            except Exception as exc:
                logger.exception("is_language_button check failed: %s", exc)
                return False

        dp.message.register(self.handle_language_button, is_language_button)

        async def is_help_button(message):
            if not message.text:
                return False
            try:
                return any(
                    locale.get("btn_help") == message.text
                    for locale in LOCALES.values()
                )
            except Exception as exc:
                logger.exception("is_help_button check failed: %s", exc)
                return False

        dp.message.register(self.handle_help_button, is_help_button)

        async def is_premium_button(message):
            if not message.text:
                return False
            try:
                return any(
                    locale.get("btn_premium") == message.text
                    for locale in LOCALES.values()
                )
            except Exception as exc:
                logger.exception("is_premium_button check failed: %s", exc)
                return False

        dp.message.register(self.handle_premium_button, is_premium_button)

        async def is_ping_text(message):
            if not message.text:
                return False
            return message.text.strip().lower() == "ping"

        dp.message.register(self.handle_ping_text, is_ping_text)

    def register_fallback(self, dp):
        """Register the last-resort text handler after feature handlers."""

        async def is_plain_unrecognized_text(message):
            if not message.text or not message.from_user:
                return False
            return not message.text.startswith("/")

        dp.message.register(self.handle_unrecognized_text, is_plain_unrecognized_text)












