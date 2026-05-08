"""Message handlers for the Trending feature."""

import logging

from aiogram import types

from localization import LOCALES
from logging_utils import action_event, actor_label
from scraper import get_trending_by_search_top3_async
from services.trending_service import (
    TREND_SEARCH_AWAIT,
    format_trending_items,
    trending_menu_kb,
    trending_results_kb,
)

from .base import BaseHandler

logger = logging.getLogger(__name__)


class TrendingHandler(BaseHandler):
    """Handle Trending reply-keyboard entry and search query input."""

    @staticmethod
    def _looks_like_supported_product_link(text: str) -> bool:
        text_lower = (text or "").lower()
        return "trendyol.com" in text_lower or "ty.gl/" in text_lower

    async def _is_trending_button(self, message: types.Message) -> bool:
        if not message.text:
            return False
        try:
            text = message.text.strip()
            if self._looks_like_supported_product_link(text):
                return False

            text_lower = text.lower()
            return (
                any(locale.get("btn_trending") == text for locale in LOCALES.values())
                or text_lower in {"trend", "trends"}
            )
        except Exception as exc:
            logger.exception("Trending button check failed: %s", exc)
            return False

    async def _is_trending_search_text(self, message: types.Message) -> bool:
        if not message.text or message.text.startswith("/"):
            return False
        if self._looks_like_supported_product_link(message.text):
            return False
        return bool(message.from_user and message.from_user.id in TREND_SEARCH_AWAIT)

    async def handle_trending_button(self, message: types.Message) -> None:
        user_id = message.from_user.id
        action_event("USER", "opened trends menu", user=actor_label(message.from_user))
        await message.answer(
            self.t(user_id, "trending_header"),
            reply_markup=trending_menu_kb(user_id),
        )

    async def handle_trending_search_text(self, message: types.Message) -> None:
        user_id = message.from_user.id
        query = (message.text or "").strip()
        if not query:
            await message.answer(self.t(user_id, "trending_enter_query"))
            return

        TREND_SEARCH_AWAIT.discard(user_id)
        status_message = None
        try:
            status_message = await self.send_status_message(
                message,
                self.t(user_id, "status_loading_trends"),
            )
            items = await get_trending_by_search_top3_async(query)
            if not items:
                await self.replace_status_message(
                    status_message,
                    self.t(user_id, "trending_no_results"),
                    fallback_target=message,
                )
                return

            action_event(
                "USER",
                "searched trends",
                user=actor_label(message.from_user),
                query=query[:80],
                results=len(items),
            )
            await self.replace_status_message(
                status_message,
                self.t(user_id, "trending_header") + "\n\n" + format_trending_items(user_id, items),
                fallback_target=message,
                reply_markup=trending_results_kb(user_id, items),
                parse_mode="HTML",
            )
        except Exception as exc:
            logger.exception("Trending search error: %s", exc)
            await self.replace_status_message(
                status_message,
                self.t(user_id, "trending_no_results"),
                fallback_target=message,
            )

    def register(self, dp):
        dp.message.register(self.handle_trending_search_text, self._is_trending_search_text)
        dp.message.register(self.handle_trending_button, self._is_trending_button)
