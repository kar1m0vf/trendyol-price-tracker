"""Basic handlers for start/help/language commands."""

import logging

from aiogram import types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from database import add_user_if_not_exists, save_user_profile, set_user_language
from logging_utils import action_event, actor_label
from localization import LOCALES, update_language_cache
from .base import BaseHandler

logger = logging.getLogger(__name__)


class BasicHandler(BaseHandler):
    """Handler for basic bot commands."""

    async def handle_start(self, message: types.Message):
        """Handle /start command."""
        user_id = message.from_user.id
        add_user_if_not_exists(user_id)
        save_user_profile(message.from_user)
        action_event("USER", "opened /start", user=actor_label(message.from_user))

        try:
            lang_code = (message.from_user.language_code or "").split("-")[0].lower()
        except Exception as exc:
            logger.debug("Could not determine user language_code: %s", exc)
            lang_code = ""

        preferred = lang_code if lang_code in LOCALES else "en"

        try:
            set_user_language(user_id, preferred)
            update_language_cache(user_id, preferred)
        except Exception as exc:
            logger.exception("Failed to set user language: %s", exc)

        from keyboards import get_main_kb

        await message.answer(
            self.t(user_id, "start_text"),
            reply_markup=get_main_kb(user_id),
            parse_mode="Markdown",
        )

    async def handle_help(self, message: types.Message):
        """Handle /help command."""
        user_id = message.from_user.id
        args = (message.text or "").split(maxsplit=1)
        if len(args) > 1 and args[1].strip().lower() == "full":
            await message.answer(self.t(user_id, "help_full"))
            return

        help_keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=self.t(user_id, "btn_detailed_help"),
                        callback_data="help:full",
                    )
                ]
            ]
        )
        await message.answer(self.t(user_id, "help_text"), reply_markup=help_keyboard)

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
                    from keyboards import get_main_kb

                    await self.bot.send_message(
                        user_id,
                        self.t(user_id, "start_text"),
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

    def register(self, dp):
        """Register all handlers."""
        dp.message.register(self.handle_start, Command("start"))
        dp.message.register(self.handle_help, Command("help"))
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












