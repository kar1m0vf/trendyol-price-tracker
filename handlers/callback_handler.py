"""
Handlers for callback queries (button clicks).
"""
from datetime import datetime
import sys

from aiogram import types
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
import html
import re

from .base import BaseHandler
from database import (
    get_subscription, remove_subscription, remove_subscriptions_by_user,
    update_mode, set_user_language, update_subscription_settings,
    update_last_price, update_subscription_meta,
    get_price_history, add_price_point, save_price_point, get_user_subscriptions,
    get_user_language, get_bot_text, get_recommended_products,
    remove_recommended_product, record_subscription_check_failure,
    clear_subscription_check_failure, get_subscription_active,
    get_subscription_failure_details, set_subscription_active
)
from keyboards import subscription_controls_kb_for_user, get_main_kb
from logging_utils import action_event, actor_label
from localization import update_language_cache
from user_texts import format_start_text
from scraper import get_product_info_async
from services.trending_service import (
    TREND_SEARCH_AWAIT,
    format_trending_items,
    get_cached_trending_items,
    set_cached_trending_items,
    trending_cache_key,
    trending_categories_kb,
    trending_menu_kb,
    trending_results_kb,
)
import sqlite3
import logging

logger = logging.getLogger(__name__)


def _safe_html(value) -> str:
    return html.escape("" if value is None else str(value), quote=False)


class CallbackHandler(BaseHandler):
    """Handler for callback queries from inline keyboards."""

    @staticmethod
    def _event_bot(cq: CallbackQuery):
        for obj in (cq, getattr(cq, "message", None)):
            if obj is None:
                continue
            try:
                candidate = getattr(obj, "bot", None)
            except Exception:
                continue
            if candidate is not None:
                return candidate
        return None

    @staticmethod
    def _set_report_state(user_id: int, state: dict) -> bool:
        updated = False
        for module_name in ("__main__", "bot"):
            module = sys.modules.get(module_name)
            report_state = getattr(module, "report_state", None) if module else None
            if isinstance(report_state, dict):
                report_state[user_id] = dict(state)
                updated = True
        return updated

    async def _send_callback_problem(self, cq: CallbackQuery, user_id: int, text: str = "") -> None:
        """Send a durable error message for callbacks that cannot finish."""
        message_text = text or self.t(user_id, "error_generic")
        try:
            await cq.answer(message_text, show_alert=True)
        except Exception:
            logger.debug("Failed to answer callback error", exc_info=True)

        message = getattr(cq, "message", None)
        if message is not None:
            try:
                await message.answer(message_text)
                return
            except Exception:
                logger.debug("Failed to send durable callback error", exc_info=True)

    async def _replace_callback_message(self, cq: CallbackQuery, text: str, **kwargs) -> None:
        """Replace text/caption behind a callback, falling back to a new message."""
        message = getattr(cq, "message", None)
        if message is None:
            return

        try:
            await message.edit_text(text, **kwargs)
            return
        except TelegramBadRequest as exc:
            message_text = str(exc).lower()
            if "no text" not in message_text and "message is not modified" not in message_text:
                raise
            if "message is not modified" in message_text:
                return

        caption_kwargs = {
            key: value
            for key, value in kwargs.items()
            if key in {"reply_markup", "parse_mode", "caption_entities"}
        }
        edit_caption = getattr(message, "edit_caption", None)
        if callable(edit_caption):
            try:
                await edit_caption(caption=text, **caption_kwargs)
                return
            except TelegramBadRequest as exc:
                message_text = str(exc).lower()
                if "message is not modified" in message_text:
                    return
                logger.debug("Could not edit callback message caption", exc_info=True)

        answer = getattr(message, "answer", None)
        if callable(answer):
            await answer(text, **kwargs)
            return
        raise RuntimeError("Callback message cannot be edited or answered")

    async def _show_product_card_message(
        self,
        cq: CallbackQuery,
        user_id: int,
        text: str,
        *,
        image: str = "",
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> None:
        if image and len(text) <= 1024:
            message = getattr(cq, "message", None)
            photo_kwargs = {
                "reply_markup": reply_markup,
                "parse_mode": "HTML",
            }

            edit_caption = getattr(message, "edit_caption", None) if message is not None else None
            if callable(edit_caption):
                try:
                    await edit_caption(caption=text, **photo_kwargs)
                    return
                except TelegramBadRequest as exc:
                    message_text = str(exc).lower()
                    if "message is not modified" in message_text:
                        return
                    logger.debug("Could not edit product card caption", exc_info=True)
                except Exception:
                    logger.debug("Could not edit product card caption", exc_info=True)

            answer_photo = getattr(message, "answer_photo", None) if message is not None else None
            if callable(answer_photo):
                try:
                    await answer_photo(photo=image, caption=text, **photo_kwargs)
                    return
                except Exception:
                    logger.debug("Could not send product card photo from callback message", exc_info=True)

            try:
                await self.bot.send_photo(user_id, photo=image, caption=text, **photo_kwargs)
                return
            except Exception:
                logger.debug("Could not send product card photo via bot", exc_info=True)

        await self._replace_callback_message(
            cq,
            text,
            reply_markup=reply_markup,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

    async def handle_main_callback(self, cq: CallbackQuery):
        """Handle main callback queries."""
        data = cq.data or ""
        user_id = cq.from_user.id
        self.bind_runtime_bot(self._event_bot(cq))
        logger.debug("Callback received: data=%r user=%s", data, user_id)

        try:

            if data == "help:full":
                await cq.answer()
                await cq.message.edit_text(self.t(user_id, "help_full"))
                return

            if data == "onboarding:add":
                await cq.answer()
                await cq.message.answer(
                    self.t(user_id, "send_link_prompt"),
                    reply_markup=get_main_kb(user_id),
                )
                return

            if data == "subs:list":
                await cq.answer()
                action_event("USER", "opened subscriptions from button", user=actor_label(cq.from_user))
                await self._show_subscriptions_overview(cq, user_id)
                return

            if data == "premium:request":
                await cq.answer()
                if not self._set_report_state(
                    user_id,
                    {"step": "waiting_text", "source": "premium_request"},
                ):
                    await self._send_callback_problem(cq, user_id)
                    return
                await cq.message.answer(
                    self.t(user_id, "premium_request_prompt"),
                    parse_mode="HTML",
                )
                return


            if data.startswith("lang:"):
                await cq.answer()
                lang = data.split(":", 1)[1]
                set_user_language(user_id, lang)
                update_language_cache(user_id, lang)
                action_event("USER", "changed language", user=actor_label(cq.from_user), language=lang)
                try:
                    await self.bot.send_message(
                        user_id,
                        format_start_text(user_id, cq.from_user, self.t),
                        reply_markup=get_main_kb(user_id),
                        parse_mode="Markdown",
                    )
                    await cq.message.edit_text(self.t(user_id, "lang_changed"))
                except Exception as e:
                    logger.warning("Failed to update language UI for %s: %s", user_id, e)
                return



            if data.startswith("trend:"):
                parts = data.split(":")
                if (len(parts) >= 2 and parts[1] == "all") or (len(parts) >= 3 and parts[1] == "cat"):
                    from bot import check_heavy_command_rate_limit

                    cache_key = (
                        trending_cache_key("all")
                        if parts[1] == "all"
                        else trending_cache_key("cat", parts[2])
                    )
                    refresh_callback = "trend:all" if parts[1] == "all" else f"trend:cat:{parts[2]}"
                    rate_limit_key = "trending_all" if parts[1] == "all" else f"trending_cat:{parts[2]}"
                    retry_after = check_heavy_command_rate_limit(user_id, rate_limit_key)
                    if retry_after:
                        cached_items = get_cached_trending_items(cache_key)
                        if cached_items:
                            await cq.answer()
                            await self.replace_status_message(
                                cq.message,
                                self.t(user_id, "trending_header") + "\n\n" + format_trending_items(user_id, cached_items),
                                fallback_target=user_id,
                                reply_markup=trending_results_kb(
                                    user_id,
                                    cached_items,
                                    refresh_callback=refresh_callback,
                                ),
                                parse_mode="HTML",
                            )
                            return
                        await cq.answer(
                            self.t(user_id, "heavy_command_rate_limited", seconds=retry_after),
                            show_alert=True,
                        )
                        return
                await cq.answer()
                status_message = None
                try:

                    if len(parts) >= 2 and parts[1] == "menu":
                        await cq.message.edit_text(
                            self.t(user_id, "trending_header"),
                            reply_markup=trending_menu_kb(user_id),
                        )
                        return

                    if len(parts) >= 2 and parts[1] == "all":
                        from scraper import get_trending_all_top3_async
                        try:
                            await cq.message.edit_text(self.t(user_id, "status_loading_trends"), reply_markup=None)
                            status_message = cq.message
                        except Exception:
                            status_message = await self.send_status_message(
                                user_id,
                                self.t(user_id, "status_loading_trends"),
                            )
                        items = await get_trending_all_top3_async()
                        if not items:
                            await self.replace_status_message(
                                status_message,
                                self.t(user_id, "trending_unavailable"),
                                fallback_target=user_id,
                                reply_markup=trending_menu_kb(user_id),
                            )
                            return
                        set_cached_trending_items(trending_cache_key("all"), items)
                        header = self.t(user_id, "trending_header")
                        await self.replace_status_message(
                            status_message,
                            header + "\n\n" + format_trending_items(user_id, items),
                            fallback_target=user_id,
                            reply_markup=trending_results_kb(user_id, items),
                            parse_mode="HTML",
                        )
                        return


                    if len(parts) >= 2 and parts[1] == "catmenu":
                        kb = trending_categories_kb(user_id)
                        await cq.message.edit_text(self.t(user_id, "trending_choose_category"), reply_markup=kb)
                        return


                    if len(parts) >= 2 and parts[1] == "search":
                        TREND_SEARCH_AWAIT.add(user_id)
                        await cq.message.edit_text(self.t(user_id, "trending_enter_query"))
                        return


                    if len(parts) >= 3 and parts[1] == "cat":
                        cat_key = parts[2]
                        from scraper import get_trending_by_category_top3_async
                        try:
                            await cq.message.edit_text(self.t(user_id, "status_loading_trends"), reply_markup=None)
                            status_message = cq.message
                        except Exception:
                            status_message = await self.send_status_message(
                                user_id,
                                self.t(user_id, "status_loading_trends"),
                            )
                        items = await get_trending_by_category_top3_async(cat_key)
                        if not items:
                            await self.replace_status_message(
                                status_message,
                                self.t(user_id, "trending_no_results"),
                                fallback_target=user_id,
                                reply_markup=trending_categories_kb(user_id),
                            )
                            return
                        set_cached_trending_items(trending_cache_key("cat", cat_key), items)
                        await self.replace_status_message(
                            status_message,
                            self.t(user_id, "trending_header") + "\n\n" + format_trending_items(user_id, items),
                            fallback_target=user_id,
                            reply_markup=trending_results_kb(
                                user_id,
                                items,
                                refresh_callback=f"trend:cat:{cat_key}",
                            ),
                            parse_mode="HTML",
                        )
                        return

                except Exception as e:
                    logger.exception("Trending callback error: %s", e)
                    if status_message is not None:
                        await self.replace_status_message(
                            status_message,
                            self.t(user_id, "error_generic"),
                            fallback_target=user_id,
                        )
                    else:
                        await cq.answer(self.t(user_id, "error_generic"), show_alert=True)
                return


            if data == "compare_cancel":
                from bot import _clear_compare_state

                _clear_compare_state(user_id)
                await cq.answer()
                await self._replace_callback_message(cq, self.t(user_id, "action_cancelled"))
                return

            if data == "compare_subs":
                from bot import (
                    _compare_subscription_matches_first,
                    _compare_subscriptions_keyboard,
                    _compare_prompt_keyboard,
                    compare_state,
                )

                await cq.answer()
                subs = get_user_subscriptions(user_id)
                if not subs:
                    await self._replace_callback_message(cq, self.t(user_id, "no_subs"))
                    return
                first = (compare_state.get(user_id) or {}).get("first")
                selectable_subs = [
                    sub
                    for sub in subs
                    if not _compare_subscription_matches_first(sub, first)
                ]
                if not selectable_subs:
                    await self._replace_callback_message(
                        cq,
                        self.t(user_id, "compare_no_other_subs"),
                        reply_markup=_compare_prompt_keyboard(user_id),
                        parse_mode="HTML",
                        disable_web_page_preview=True,
                    )
                    return
                await self._replace_callback_message(
                    cq,
                    self.t(user_id, "compare_choose_subscription"),
                    reply_markup=_compare_subscriptions_keyboard(user_id, subs, first),
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
                return

            if data.startswith("compare_pick:"):
                from bot import (
                    _clear_compare_state,
                    _compare_product_from_subscription,
                    _compare_prompt_keyboard,
                    _compare_products_by_urls,
                    _set_compare_first,
                    normalize_url,
                    compare_state,
                )

                try:
                    sub_id = int(data.split(":", 1)[1])
                    sub = get_subscription(sub_id)
                    if not sub or sub[1] != user_id:
                        await cq.answer(self.t(user_id, "error_not_your_sub"), show_alert=True)
                        return

                    product = _compare_product_from_subscription(sub)
                    state = compare_state.get(user_id) or {}
                    first = state.get("first")
                    if first and first.get("url"):
                        same_sub = (
                            first.get("sub_id") is not None
                            and first.get("sub_id") == product.get("sub_id")
                        )
                        same_url = (
                            normalize_url(first.get("url") or "").lower()
                            == normalize_url(product.get("url") or "").lower()
                        )
                        if same_sub or same_url:
                            await cq.answer(self.t(user_id, "compare_same_product"), show_alert=True)
                            return

                        await cq.answer()
                        await self._replace_callback_message(
                            cq,
                            self.t(user_id, "status_loading_compare"),
                            parse_mode="HTML",
                            disable_web_page_preview=True,
                        )
                        _clear_compare_state(user_id)
                        await _compare_products_by_urls(
                            user_id,
                            first["url"],
                            product["url"],
                            apply_rate_limit=False,
                            status_message=getattr(cq, "message", None),
                            fallback_target=user_id,
                        )
                        return

                    _set_compare_first(user_id, product)
                    await cq.answer()
                    await self._replace_callback_message(
                        cq,
                        self.t(user_id, "compare_first_added"),
                        reply_markup=_compare_prompt_keyboard(user_id),
                        parse_mode="HTML",
                        disable_web_page_preview=True,
                    )
                except ValueError:
                    await cq.answer(self.t(user_id, "error_invalid_id"), show_alert=True)
                except Exception as e:
                    logger.exception("compare pick callback error: %s", e)
                    await cq.answer(self.t(user_id, "error_generic"), show_alert=True)
                return

            if data.startswith("compare:"):
                from bot import (
                    _compare_product_from_subscription,
                    _compare_prompt_keyboard,
                    _set_compare_first,
                )

                try:
                    sub_id = int(data.split(":", 1)[1])
                    sub = get_subscription(sub_id)
                    if not sub or sub[1] != user_id:
                        await cq.answer(self.t(user_id, "error_not_your_sub"), show_alert=True)
                        return

                    _set_compare_first(user_id, _compare_product_from_subscription(sub))
                    await cq.answer()
                    try:
                        await cq.message.answer(
                            self.t(user_id, "compare_prompt_button"),
                            reply_markup=_compare_prompt_keyboard(user_id),
                            parse_mode="HTML",
                            disable_web_page_preview=True,
                        )
                    except Exception:
                        await self.bot.send_message(
                            user_id,
                            self.t(user_id, "compare_prompt_button"),
                            reply_markup=_compare_prompt_keyboard(user_id),
                            parse_mode="HTML",
                            disable_web_page_preview=True,
                        )
                except ValueError:
                    await cq.answer(self.t(user_id, "error_invalid_id"), show_alert=True)
                except Exception as e:
                    logger.exception("compare callback error: %s", e)
                    await cq.answer(self.t(user_id, "error_generic"), show_alert=True)
                return
            if data.startswith(("unsubscribe:", "delete:")):
                try:
                    sub_id = int(data.split(":", 1)[1])
                    sub = get_subscription(sub_id)
                    if sub and sub[1] == user_id:
                        title = html.escape(str(sub[5] or sub[2] or "").strip())
                        confirm_text = self.t(user_id, "confirm_unsubscribe_one")
                        if title:
                            confirm_text = f"{confirm_text}\n\n<b>{title}</b>"
                        kb = InlineKeyboardMarkup(inline_keyboard=[
                            [
                                InlineKeyboardButton(
                                    text=self.t(user_id, "btn_confirm_delete"),
                                    callback_data=f"confirm_unsub:{sub_id}:yes",
                                ),
                                InlineKeyboardButton(
                                    text=self.t(user_id, "btn_cancel"),
                                    callback_data=f"confirm_unsub:{sub_id}:no",
                                ),
                            ],
                            [
                                InlineKeyboardButton(
                                    text=self.t(user_id, "btn_subscription_settings"),
                                    callback_data=f"sub_settings:{sub_id}",
                                )
                            ],
                        ])
                        await self._replace_callback_message(
                            cq,
                            confirm_text,
                            reply_markup=kb,
                            parse_mode="HTML",
                            disable_web_page_preview=True,
                        )
                    else:
                        await cq.answer(self.t(user_id, "error_not_your_sub"), show_alert=True)
                except ValueError:
                    await cq.answer(self.t(user_id, "error_invalid_id"), show_alert=True)
                except sqlite3.DatabaseError as e:
                    logger.error("Database error in unsubscribe/delete: %s", e)
                    await cq.answer(self.t(user_id, "error_database"), show_alert=True)
                except Exception as e:
                    logger.exception("Unsubscribe/delete error: %s", e)
                    await cq.answer(self.t(user_id, "error_generic"), show_alert=True)
                return

            if data.startswith("confirm_unsub:"):
                try:
                    _prefix, sub_id_raw, answer = data.split(":", 2)
                    sub_id = int(sub_id_raw)
                    if answer != "yes":
                        await self._replace_callback_message(cq, self.t(user_id, "action_cancelled"))
                        return

                    sub = get_subscription(sub_id)
                    if sub and sub[1] == user_id:
                        remove_subscription(sub_id)
                        action_event("USER", "removed subscription from button", user=actor_label(cq.from_user), sub_id=sub_id)
                        await self._replace_callback_message(cq, self.t(user_id, "sub_removed"))
                    else:
                        await cq.answer(self.t(user_id, "error_not_your_sub"), show_alert=True)
                except ValueError:
                    await cq.answer(self.t(user_id, "error_invalid_id"), show_alert=True)
                except sqlite3.DatabaseError as e:
                    logger.error("Database error in confirm_unsub: %s", e)
                    await cq.answer(self.t(user_id, "error_database"), show_alert=True)
                except Exception as e:
                    logger.exception("Confirm unsubscribe error: %s", e)
                    await cq.answer(self.t(user_id, "error_generic"), show_alert=True)
                return


            if data.startswith("confirm_unsub_all:"):
                await cq.answer()
                try:
                    ans = data.split(":", 1)[1]
                    if ans == "yes":
                        remove_subscriptions_by_user(user_id)
                        action_event("USER", "removed all subscriptions", user=actor_label(cq.from_user))
                        await cq.message.edit_text(self.t(user_id, "unsubscribed_all"))
                    else:
                        await cq.message.edit_text(self.t(user_id, "action_cancelled"))
                except Exception as e:
                    logger.exception("Mass unsubscribe error: %s", e)
                    await cq.message.edit_text(self.t(user_id, "error_generic"))
                return


            if data.startswith("mode:"):
                parts = data.split(":")
                if len(parts) == 3:
                    _, sub_id_str, mode = parts
                    try:
                        sub_id = int(sub_id_str)
                        sub = get_subscription(sub_id)

                        if not sub:
                            await cq.answer(self.t(user_id, "no_subs"), show_alert=True)
                            return


                        owner_ok = len(sub) >= 2 and sub[1] == user_id
                        if not owner_ok:
                            await cq.answer(self.t(user_id, "error_not_your_sub"), show_alert=True)
                            return

                        try:
                            update_mode(sub_id, mode)
                            action_event(
                                "USER",
                                "changed subscription mode",
                                user=actor_label(cq.from_user),
                                sub_id=sub_id,
                                mode=mode,
                            )
                        except Exception as e:
                            logger.exception("Update mode error for sub %s: %s", sub_id, e)
                            await cq.answer(self.t(user_id, "error_generic"), show_alert=True)
                            return


                        try:
                            await cq.message.edit_reply_markup(reply_markup=subscription_controls_kb_for_user(user_id, sub_id))
                            await cq.answer(self.t(user_id, "mode_changed_short").format(mode=mode))
                        except Exception as e:
                            logger.exception("Mode callback UI update failed: %s", e)
                            await cq.answer(self.t(user_id, "mode_changed_short").format(mode=mode))

                    except ValueError:
                        await cq.answer(self.t(user_id, "error_generic"), show_alert=True)
                    except Exception as e:
                        logger.exception("Mode callback error: %s", e)
                        await cq.answer(self.t(user_id, "error_generic"), show_alert=True)
                return


            if data.startswith("edit_sub:"):
                try:
                    sub_id = int(data.split(":", 1)[1])
                except ValueError:
                    await cq.answer(self.t(user_id, "error_invalid_id"), show_alert=True)
                    return
                await self._show_subscription_detail(cq, user_id, sub_id, self.t(user_id, "loading"))
                return

            if data.startswith("alert_edit:"):
                try:
                    sub_id = int(data.split(":", 1)[1])
                except ValueError:
                    await cq.answer(self.t(user_id, "error_invalid_id"), show_alert=True)
                    return
                await self._handle_alert_edit(cq, user_id, sub_id)
                return

            if data.startswith("alert_remove:"):
                try:
                    sub_id = int(data.split(":", 1)[1])
                except ValueError:
                    await cq.answer(self.t(user_id, "error_invalid_id"), show_alert=True)
                    return
                await self._handle_alert_remove(cq, user_id, sub_id)
                return

            if data == "alerts_back":
                await cq.answer()
                await self._show_alerts_list(cq, user_id)
                return

            if data.startswith("sub_settings:"):
                try:
                    sub_id = int(data.split(":", 1)[1])
                except ValueError:
                    await cq.answer(self.t(user_id, "error_invalid_id"), show_alert=True)
                    return
                await self._show_subscription_settings(cq, user_id, sub_id)
                return

            if data.startswith("settings_mode:"):
                parts = data.split(":")
                if len(parts) != 3:
                    await cq.answer(self.t(user_id, "error_invalid_id"), show_alert=True)
                    return
                try:
                    sub_id = int(parts[1])
                except ValueError:
                    await cq.answer(self.t(user_id, "error_invalid_id"), show_alert=True)
                    return
                await self._handle_settings_mode(cq, user_id, sub_id, parts[2])
                return

            if data.startswith("settings_interval:"):
                parts = data.split(":")
                if len(parts) != 3:
                    await cq.answer(self.t(user_id, "error_invalid_id"), show_alert=True)
                    return
                try:
                    sub_id = int(parts[1])
                    minutes = int(parts[2])
                except ValueError:
                    await cq.answer(self.t(user_id, "error_invalid_id"), show_alert=True)
                    return
                await self._handle_settings_interval(cq, user_id, sub_id, minutes)
                return

            if data.startswith("settings_alert_edit:"):
                try:
                    sub_id = int(data.split(":", 1)[1])
                except ValueError:
                    await cq.answer(self.t(user_id, "error_invalid_id"), show_alert=True)
                    return
                await self._handle_settings_alert_edit(cq, user_id, sub_id)
                return

            if data.startswith("settings_alert_remove:"):
                try:
                    sub_id = int(data.split(":", 1)[1])
                except ValueError:
                    await cq.answer(self.t(user_id, "error_invalid_id"), show_alert=True)
                    return
                await self._handle_settings_alert_remove(cq, user_id, sub_id)
                return

            if data.startswith("settings_toggle_active:"):
                try:
                    sub_id = int(data.split(":", 1)[1])
                except ValueError:
                    await cq.answer(self.t(user_id, "error_invalid_id"), show_alert=True)
                    return
                await self._handle_toggle_subscription_active(cq, user_id, sub_id, source="settings")
                return

            if data.startswith("settings_back:"):
                try:
                    sub_id = int(data.split(":", 1)[1])
                except ValueError:
                    await cq.answer(self.t(user_id, "error_invalid_id"), show_alert=True)
                    return
                await self._show_subscription_detail(cq, user_id, sub_id)
                return

            if data.startswith("toggle_active:"):
                try:
                    sub_id = int(data.split(":", 1)[1])
                except ValueError:
                    await cq.answer(self.t(user_id, "error_invalid_id"), show_alert=True)
                    return
                await self._handle_toggle_subscription_active(cq, user_id, sub_id, source="detail")
                return

            if data.startswith("refresh_price:"):
                try:
                    sub_id = int(data.split(":", 1)[1])
                except ValueError:
                    await cq.answer(self.t(user_id, "error_invalid_id"), show_alert=True)
                    return
                await self._handle_refresh_price(cq, user_id, sub_id)
                return

            if data.startswith("history:"):
                try:
                    sub_id = int(data.split(":", 1)[1])
                except ValueError:
                    await cq.answer(self.t(user_id, "error_invalid_id"), show_alert=True)
                    return
                await self._handle_history(cq, user_id, sub_id)
                return

            if data.startswith("admin_"):
                handled = await self._handle_admin_callback(cq, data, user_id)
                if handled:
                    return

            await cq.answer(self.t(user_id, "error_generic"), show_alert=True)

        except Exception as e:
            logger.exception("Main callback handler error: %s", e)
            await self._send_callback_problem(cq, user_id)

    @staticmethod
    def _short_title(title, url, limit=90):
        raw = (title or "").strip() or (url or "")
        raw = re.sub(r"\s+", " ", raw)
        if len(raw) <= limit:
            return raw
        return raw[: max(0, limit - 3)].rstrip() + "..."

    def _format_price(self, user_id, price):
        if price is None:
            return self.t(user_id, "unknown_price")
        try:
            return f"{float(price):.0f} TL"
        except (TypeError, ValueError):
            return self.t(user_id, "unknown_price")

    @staticmethod
    def _subscription_values(sub):
        values = list(sub or [])
        while len(values) < 13:
            values.append(None)
        return values[:13]

    @staticmethod
    def _set_alert_edit_state(user_id: int, sub_id: int) -> None:
        updated = False
        for module_name in ("__main__", "bot"):
            module = sys.modules.get(module_name)
            state = getattr(module, "alert_edit_state", None) if module else None
            if isinstance(state, dict):
                state[user_id] = sub_id
                updated = True

        if not updated:
            from bot import alert_edit_state

            alert_edit_state[user_id] = sub_id

    @staticmethod
    def _price_changed(old_price, new_price) -> bool:
        if old_price is None:
            return True
        try:
            return round(float(old_price), 2) != round(float(new_price), 2)
        except (TypeError, ValueError):
            return True

    @staticmethod
    def _format_price_change(old_price, new_price) -> str:
        try:
            old_value = float(old_price)
            new_value = float(new_price)
        except (TypeError, ValueError):
            return ""

        diff = new_value - old_value
        if abs(diff) < 0.005:
            return "0 TL"

        sign = "+" if diff > 0 else ""
        diff_text = f"{sign}{diff:.0f} TL"
        if old_value:
            percent = diff / old_value * 100
            percent_sign = "+" if percent > 0 else ""
            diff_text += f" ({percent_sign}{percent:.1f}%)"
        return diff_text

    @staticmethod
    def _safe_ts_to_iso(ts_val):
        if ts_val is None:
            return ""
        if isinstance(ts_val, (int, float)):
            try:
                return datetime.fromtimestamp(int(ts_val)).isoformat()
            except Exception:
                return str(ts_val)
        if isinstance(ts_val, str):
            try:
                datetime.fromisoformat(ts_val)
                return ts_val
            except Exception:
                try:
                    return datetime.strptime(ts_val, "%d.%m.%Y").isoformat()
                except Exception:
                    return ts_val
        return str(ts_val)

    def _subscription_detail_keyboard(self, user_id: int, sub_id: int) -> InlineKeyboardMarkup:
        controls = subscription_controls_kb_for_user(user_id, sub_id)
        rows = [list(row) for row in controls.inline_keyboard]
        rows.append([
            InlineKeyboardButton(
                text=f"⬅️ {self.t(user_id, 'btn_back')}",
                callback_data="subs:list",
            )
        ])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    def _subscription_settings_keyboard(self, user_id: int, sub) -> InlineKeyboardMarkup:
        (
            sub_id, _owner_id, _url, mode, _last_price, _title, _image,
            _min_price, _max_price, _notify_percent, notify_interval,
            _last_notify_time, price_alert,
        ) = self._subscription_values(sub)

        mode_label_discount = self.t(user_id, "btn_mode_discount")
        mode_label_hourly = self.t(user_id, "btn_mode_hourly")
        if mode == "discount":
            mode_label_discount = "✅ " + mode_label_discount
        elif mode == "hourly":
            mode_label_hourly = "✅ " + mode_label_hourly

        try:
            interval = int(notify_interval or 60)
        except (TypeError, ValueError):
            interval = 60

        try:
            is_active = get_subscription_active(sub_id)
        except Exception:
            logger.exception("Failed to read active state for subscription %s", sub_id)
            is_active = True

        def interval_label(minutes: int) -> str:
            prefix = "✅ " if interval == minutes else ""
            return f"{prefix}{minutes} min"

        rows = [
            [
                InlineKeyboardButton(
                    text=mode_label_discount,
                    callback_data=f"settings_mode:{sub_id}:discount",
                ),
                InlineKeyboardButton(
                    text=mode_label_hourly,
                    callback_data=f"settings_mode:{sub_id}:hourly",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=interval_label(15),
                    callback_data=f"settings_interval:{sub_id}:15",
                ),
                InlineKeyboardButton(
                    text=interval_label(30),
                    callback_data=f"settings_interval:{sub_id}:30",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=interval_label(60),
                    callback_data=f"settings_interval:{sub_id}:60",
                ),
                InlineKeyboardButton(
                    text=interval_label(180),
                    callback_data=f"settings_interval:{sub_id}:180",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=self.t(user_id, "btn_price_alert"),
                    callback_data=f"settings_alert_edit:{sub_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text=self.t(user_id, "btn_pause_subscription" if is_active else "btn_resume_subscription"),
                    callback_data=f"settings_toggle_active:{sub_id}",
                )
            ],
        ]
        if price_alert is not None:
            rows.append([
                InlineKeyboardButton(
                    text=f"❌ {self.t(user_id, 'alerts_remove')}",
                    callback_data=f"settings_alert_remove:{sub_id}",
                )
            ])
        rows.append([
            InlineKeyboardButton(
                text=f"⬅️ {self.t(user_id, 'btn_back')}",
                callback_data=f"settings_back:{sub_id}",
            )
        ])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    def _subscription_settings_text(self, user_id: int, sub) -> str:
        (
            sub_id, _owner_id, url, mode, last_price, product_title, _image,
            _min_price, _max_price, _notify_percent, notify_interval,
            _last_notify_time, price_alert,
        ) = self._subscription_values(sub)

        title = html.escape(self._short_title(product_title, url, limit=90))
        price = html.escape(self._format_price(user_id, last_price))
        mode_text = html.escape(
            self.t(user_id, f"mode_{mode}")
            if mode in {"discount", "hourly"}
            else self.t(user_id, "next_notify_unknown")
        )
        try:
            interval = int(notify_interval or 60)
        except (TypeError, ValueError):
            interval = 60
        target = (
            html.escape(self._format_price(user_id, price_alert))
            if price_alert is not None
            else html.escape(self.t(user_id, "alerts_not_set"))
        )
        try:
            is_active = get_subscription_active(sub_id)
        except Exception:
            logger.exception("Failed to read active state for subscription %s", sub_id)
            is_active = True
        status = html.escape(
            self.t(user_id, "status_active" if is_active else "status_paused")
        )
        status_icon = "\u2705" if is_active else "\u23f8\ufe0f"

        return (
            f"⚙️ <b>{html.escape(self.t(user_id, 'subscription_settings_title'))}</b>\n\n"
            f"{status_icon} {html.escape(self.t(user_id, 'subscription_settings_status'))}: {status}\n"
            f"📦 <b>{title}</b>\n"
            f"💰 {html.escape(self.t(user_id, 'current_price'))}: {price}\n"
            f"🔔 {html.escape(self.t(user_id, 'subscription_settings_mode'))}: {mode_text}\n"
            f"⏱ {html.escape(self.t(user_id, 'subscription_settings_interval'))}: {interval} min\n"
            f"🎯 {html.escape(self.t(user_id, 'subscription_settings_target'))}: {target}"
        )

    async def _show_subscriptions_overview(self, cq: CallbackQuery, user_id: int) -> None:
        from bot import build_subscriptions_overview

        subs = get_user_subscriptions(user_id)
        if not subs:
            await self._replace_callback_message(cq, self.t(user_id, "no_subs"))
            return

        overview_text, overview_keyboard = build_subscriptions_overview(user_id, subs)
        await self._replace_callback_message(
            cq,
            overview_text,
            reply_markup=overview_keyboard,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

    async def _show_subscription_detail(
        self,
        cq: CallbackQuery,
        user_id: int,
        sub_id: int,
        notice: str = "",
    ) -> None:
        from bot import format_subscription_card

        sub = get_subscription(sub_id)
        if not sub or sub[1] != user_id:
            await cq.answer(self.t(user_id, "error_not_your_sub"), show_alert=True)
            return

        await cq.answer(notice or None)
        text = (
            f"⚙️ <b>{html.escape(self.t(user_id, 'edit_subscription'))}</b>\n\n"
            + format_subscription_card(user_id, sub)
        )
        product_image = str(self._subscription_values(sub)[6] or "").strip()
        await self._show_product_card_message(
            cq,
            user_id,
            text,
            image=product_image,
            reply_markup=self._subscription_detail_keyboard(user_id, sub_id),
        )

    async def _show_subscription_settings(
        self,
        cq: CallbackQuery,
        user_id: int,
        sub_id: int,
        notice: str = "",
    ) -> None:
        sub = get_subscription(sub_id)
        if not sub or sub[1] != user_id:
            await cq.answer(self.t(user_id, "error_not_your_sub"), show_alert=True)
            return

        await cq.answer(notice or None)
        await self._replace_callback_message(
            cq,
            self._subscription_settings_text(user_id, sub),
            reply_markup=self._subscription_settings_keyboard(user_id, sub),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

    async def _handle_toggle_subscription_active(
        self,
        cq: CallbackQuery,
        user_id: int,
        sub_id: int,
        *,
        source: str = "detail",
    ) -> None:
        sub = get_subscription(sub_id)
        if not sub or sub[1] != user_id:
            await cq.answer(self.t(user_id, "error_not_your_sub"), show_alert=True)
            return

        try:
            currently_active = get_subscription_active(sub_id)
        except Exception:
            logger.exception("Failed to read active state for subscription %s", sub_id)
            currently_active = True

        new_active = not currently_active
        if not set_subscription_active(sub_id, new_active):
            await cq.answer(self.t(user_id, "error_generic"), show_alert=True)
            return

        action_event(
            "USER",
            "changed subscription active state",
            user=actor_label(cq.from_user),
            sub_id=sub_id,
            active=new_active,
        )
        notice_key = "subscription_resumed" if new_active else "subscription_paused"
        if source == "settings":
            await self._show_subscription_settings(cq, user_id, sub_id, self.t(user_id, notice_key))
            return
        await self._show_subscription_detail(cq, user_id, sub_id, self.t(user_id, notice_key))

    async def _handle_settings_mode(
        self,
        cq: CallbackQuery,
        user_id: int,
        sub_id: int,
        mode: str,
    ) -> None:
        if mode not in {"discount", "hourly"}:
            await cq.answer(self.t(user_id, "error_invalid_id"), show_alert=True)
            return

        sub = get_subscription(sub_id)
        if not sub or sub[1] != user_id:
            await cq.answer(self.t(user_id, "error_not_your_sub"), show_alert=True)
            return

        update_mode(sub_id, mode)
        action_event(
            "USER",
            "changed subscription mode from settings menu",
            user=actor_label(cq.from_user),
            sub_id=sub_id,
            mode=mode,
        )
        await self._show_subscription_settings(
            cq,
            user_id,
            sub_id,
            self.t(user_id, "subscription_settings_updated"),
        )

    async def _handle_settings_interval(
        self,
        cq: CallbackQuery,
        user_id: int,
        sub_id: int,
        minutes: int,
    ) -> None:
        if minutes not in {15, 30, 60, 180}:
            await cq.answer(self.t(user_id, "error_invalid_id"), show_alert=True)
            return

        sub = get_subscription(sub_id)
        if not sub or sub[1] != user_id:
            await cq.answer(self.t(user_id, "error_not_your_sub"), show_alert=True)
            return

        update_subscription_settings(sub_id, notify_interval=minutes)
        action_event(
            "USER",
            "changed subscription interval from settings menu",
            user=actor_label(cq.from_user),
            sub_id=sub_id,
            interval=minutes,
        )
        await self._show_subscription_settings(
            cq,
            user_id,
            sub_id,
            self.t(user_id, "subscription_settings_updated"),
        )

    async def _handle_settings_alert_edit(self, cq: CallbackQuery, user_id: int, sub_id: int) -> None:
        await cq.answer()
        sub = get_subscription(sub_id)
        if not sub or sub[1] != user_id:
            await cq.answer(self.t(user_id, "error_not_your_sub"), show_alert=True)
            return

        url = sub[2]
        last_price = sub[4]
        product_title = sub[5]
        price_alert = sub[12] if len(sub) > 12 else None

        title = html.escape(self._short_title(product_title, url, limit=80))
        current_price = html.escape(self._format_price(user_id, last_price))
        current_alert = f"{price_alert:.0f} TL" if price_alert else self.t(user_id, "alerts_not_set")
        alert_text = (
            f"⚙️ <b>{html.escape(self.t(user_id, 'alerts_edit_title'))}</b>\n\n"
            f"📦 {title}\n"
            f"💰 {html.escape(self.t(user_id, 'current_price'))}: {current_price}\n"
            f"🎯 {html.escape(self.t(user_id, 'alerts_current'))}: {html.escape(current_alert)}\n\n"
            f"{self.t(user_id, 'alerts_edit_help')}"
        )
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=f"⬅️ {self.t(user_id, 'btn_back')}",
                callback_data=f"sub_settings:{sub_id}",
            )],
        ])

        await self.bot.send_message(
            user_id,
            alert_text,
            reply_markup=keyboard,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

        self._set_alert_edit_state(user_id, sub_id)

    async def _handle_settings_alert_remove(self, cq: CallbackQuery, user_id: int, sub_id: int) -> None:
        sub = get_subscription(sub_id)
        if not sub or sub[1] != user_id:
            await cq.answer(self.t(user_id, "error_not_your_sub"), show_alert=True)
            return

        update_subscription_settings(sub_id, price_alert=None)
        action_event(
            "USER",
            "removed subscription target price from settings menu",
            user=actor_label(cq.from_user),
            sub_id=sub_id,
        )
        await self._show_subscription_settings(
            cq,
            user_id,
            sub_id,
            self.t(user_id, "alerts_removed_success"),
        )

    async def _handle_alert_edit(self, cq: CallbackQuery, user_id: int, sub_id: int):
        await cq.answer()
        try:
            sub = get_subscription(sub_id)
            if not sub or sub[1] != user_id:
                await cq.answer(self.t(user_id, "error_not_your_sub"), show_alert=True)
                return

            url = sub[2]
            last_price = sub[4]
            product_title = sub[5]
            price_alert = sub[12] if len(sub) > 12 else None

            title = html.escape(self._short_title(product_title, url, limit=80))
            current_price = html.escape(self._format_price(user_id, last_price))
            current_alert = f"{price_alert:.0f} TL" if price_alert else self.t(user_id, "alerts_not_set")

            alert_text = (
                f"⚙️ <b>{html.escape(self.t(user_id, 'alerts_edit_title'))}</b>\n\n"
                f"📦 {title}\n"
                f"💰 {html.escape(self.t(user_id, 'current_price'))}: {current_price}\n"
                f"🎯 {html.escape(self.t(user_id, 'alerts_current'))}: {html.escape(current_alert)}\n\n"
                f"{self.t(user_id, 'alerts_edit_help')}"
            )

            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text=f"❌ {self.t(user_id, 'alerts_remove')}",
                    callback_data=f"alert_remove:{sub_id}",
                )],
                [InlineKeyboardButton(
                    text=f"🔙 {self.t(user_id, 'btn_back')}",
                    callback_data="alerts_back",
                )],
            ])

            await self.bot.send_message(
                user_id,
                alert_text,
                reply_markup=keyboard,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )

            self._set_alert_edit_state(user_id, sub_id)
        except Exception as e:
            logger.exception("alert_edit callback error: %s", e)
            await self._send_callback_problem(cq, user_id)

    async def _handle_alert_remove(self, cq: CallbackQuery, user_id: int, sub_id: int):
        try:
            sub = get_subscription(sub_id)
            if not sub or sub[1] != user_id:
                await cq.answer(self.t(user_id, "error_not_your_sub"), show_alert=True)
                return

            update_subscription_settings(sub_id, price_alert=None)
            await cq.message.edit_text(
                f"✅ {self.t(user_id, 'alerts_removed_success')}",
                reply_markup=None,
            )
            await cq.answer()
        except Exception as e:
            logger.exception("alert_remove callback error: %s", e)
            await self._send_callback_problem(cq, user_id)

    async def _show_alerts_list(self, cq: CallbackQuery, user_id: int):
        try:
            subs = get_user_subscriptions(user_id)
            if not subs:
                await cq.message.edit_text(self.t(user_id, "no_subs"))
                return

            lines = [self.t(user_id, "alerts_header")]
            keyboard = []

            for index, sub in enumerate(subs, start=1):
                sub_id = sub[0]
                url = sub[2]
                title = self._short_title(sub[5], url, limit=80)
                price_alert = sub[12] if len(sub) > 12 else None
                current_alert = f"{price_alert:.0f} TL" if price_alert else self.t(user_id, "alerts_not_set")
                lines.append(
                    f"📦 <b>{html.escape(title)}</b>\n"
                    f"💰 {html.escape(self.t(user_id, 'alerts_current'))}: {html.escape(current_alert)}\n"
                )
                keyboard.append([
                    InlineKeyboardButton(
                        text=f"⚙️ {self.t(user_id, 'btn_edit')} № {index}",
                        callback_data=f"alert_edit:{sub_id}",
                    )
                ])

            text = "\n".join(lines)
            if len(text) > 4000:
                await cq.message.edit_text(self.t(user_id, "alerts_too_many"), parse_mode="HTML")
                return

            await cq.message.edit_text(
                text,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
                parse_mode="HTML",
            )
        except Exception as e:
            logger.exception("alerts_back callback error: %s", e)
            await self._send_callback_problem(cq, user_id)

    async def _handle_refresh_price(self, cq: CallbackQuery, user_id: int, sub_id: int):
        sub = get_subscription(sub_id)
        if not sub or sub[1] != user_id:
            await cq.answer(self.t(user_id, "error_not_your_sub"), show_alert=True)
            return

        status_text = self.t(user_id, "status_checking_product")
        await cq.answer(status_text)
        status_message = await self.send_status_message(user_id, status_text)

        values = list(sub)
        while len(values) < 7:
            values.append(None)
        _, _, url, _, old_price, old_title, old_image = values[:7]

        try:
            new_price, new_title, new_image = await get_product_info_async(url)
            if new_price is None:
                record_subscription_check_failure(sub_id, "manual_price_not_found")
                await self.replace_status_message(
                    status_message,
                    self.t(user_id, "refresh_price_unavailable"),
                    fallback_target=user_id,
                    reply_markup=self._subscription_detail_keyboard(user_id, sub_id),
                )
                return

            new_price = float(new_price)
            title_to_store = new_title or old_title
            image_to_store = new_image or old_image
            if title_to_store != old_title or image_to_store != old_image:
                update_subscription_meta(sub_id, title_to_store, image_to_store)

            changed = self._price_changed(old_price, new_price)
            if changed:
                save_price_point(sub_id, new_price)
                update_last_price(sub_id, new_price)

            clear_subscription_check_failure(sub_id)
            action_event(
                "USER",
                "checked subscription price from button",
                user=actor_label(cq.from_user),
                sub_id=sub_id,
                changed=changed,
            )

            title = html.escape(self._short_title(title_to_store, url, limit=90))
            new_price_text = html.escape(self._format_price(user_id, new_price))
            if old_price is None:
                body = self.t(user_id, "refresh_price_loaded", price=new_price_text)
            elif changed:
                body = self.t(
                    user_id,
                    "refresh_price_updated",
                    old_price=html.escape(self._format_price(user_id, old_price)),
                    new_price=new_price_text,
                    change=html.escape(self._format_price_change(old_price, new_price)),
                )
            else:
                body = self.t(user_id, "refresh_price_unchanged", price=new_price_text)

            result_text = f"<b>{title}</b>\n\n{body}"
            await self.replace_status_message(
                status_message,
                result_text,
                fallback_target=user_id,
                reply_markup=self._subscription_detail_keyboard(user_id, sub_id),
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except Exception as e:
            logger.exception("refresh_price callback error: %s", e)
            await self.replace_status_message(
                status_message,
                self.t(user_id, "error_generic"),
                fallback_target=user_id,
            )

    async def _send_history_plot(self, user_id: int, url: str, hist) -> bool:
        from services.notification_service import NotificationService

        service = NotificationService(self.bot)
        return await service.send_history_plot(user_id, url, hist)

    async def _handle_history(self, cq: CallbackQuery, user_id: int, sub_id: int):
        await cq.answer(self.t(user_id, "status_loading_history"))
        status_message = await self.send_status_message(
            user_id,
            self.t(user_id, "status_loading_history"),
        )
        try:
            sub = get_subscription(sub_id)
            if not sub or sub[1] != user_id:
                await self.replace_status_message(
                    status_message,
                    self.t(user_id, "error_not_your_sub"),
                    fallback_target=user_id,
                )
                return

            url = sub[2]
            db_hist = get_price_history(sub_id, limit=1000)
            if db_hist and len(db_hist) >= 2:
                hist = [(self._safe_ts_to_iso(ts), price) for ts, price in db_hist]
                delivered = await self._send_history_plot(user_id, url, hist)
                if delivered:
                    await self.clear_status_message(status_message)
                else:
                    await self.replace_status_message(
                        status_message,
                        self.t(user_id, "error_generic"),
                        fallback_target=user_id,
                    )
                return

            from scraper import get_price_history_from_akakce_async

            hist = await get_price_history_from_akakce_async(url)
            if not hist:
                await self.replace_status_message(
                    status_message,
                    self.t(user_id, "history_not_found"),
                    fallback_target=user_id,
                )
                return

            for date_value, price in hist[-30:]:
                try:
                    ts = None
                    if isinstance(date_value, str):
                        try:
                            ts = int(datetime.fromisoformat(date_value).timestamp())
                        except Exception:
                            try:
                                ts = int(datetime.strptime(date_value, "%d.%m.%Y").timestamp())
                            except Exception:
                                ts = None
                    add_price_point(sub_id, url, float(price), ts=ts, source="akakce")
                except Exception:
                    logger.debug("Skipped invalid history point for sub=%s", sub_id, exc_info=True)

            delivered = await self._send_history_plot(user_id, url, hist)
            if delivered:
                await self.clear_status_message(status_message)
            else:
                await self.replace_status_message(
                    status_message,
                    self.t(user_id, "error_generic"),
                    fallback_target=user_id,
                )
        except Exception as e:
            logger.exception("history callback error: %s", e)
            await self.replace_status_message(
                status_message,
                self.t(user_id, "error_generic"),
                fallback_target=user_id,
            )

    async def _ensure_admin(self, cq: CallbackQuery, user_id: int) -> bool:
        from config import ADMIN_IDS

        if user_id not in ADMIN_IDS:
            await cq.answer(self.t(user_id, "admin_only"), show_alert=True)
            return False
        return True

    @staticmethod
    def _admin_recommend_back_keyboard():
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_recommend")]
        ])

    @staticmethod
    def _admin_recommend_list_keyboard():
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📋 Посмотреть список", callback_data="admin_recommend_list")]
        ])

    async def _handle_admin_recommend_action(self, cq: CallbackQuery, action: str, user_id: int):
        if action == "list":
            from handlers.admin_handler import _admin_recommend_list

            await _admin_recommend_list(cq.message)
            return

        if action == "add":
            await cq.message.edit_text(
                "➕ <b>Добавление товара</b>\n\n"
                "Используйте команду:\n"
                "<code>/admin recommend add \"Название\" \"https://ссылка\"</code>\n\n"
                "Пример:\n"
                "<code>/admin recommend add \"iPhone 15 Pro\" \"https://trendyol.com/iphone-p-123\"</code>",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="📚 Справка по формату", callback_data="admin_recommend_help")]
                ]),
                parse_mode="HTML",
            )
            return

        if action == "remove":
            await cq.message.edit_text(
                "🗑️ <b>Удаление товара</b>\n\n"
                "Используйте команду:\n"
                "<code>/admin recommend remove ID</code>\n\n"
                "Сначала посмотрите список товаров:",
                reply_markup=self._admin_recommend_list_keyboard(),
                parse_mode="HTML",
            )
            return

        if action == "priority":
            await cq.message.edit_text(
                "⭐ <b>Изменение приоритета</b>\n\n"
                "Используйте команду:\n"
                "<code>/admin recommend priority ID приоритет</code>\n\n"
                "Пример: <code>/admin recommend priority 5 10</code>",
                reply_markup=self._admin_recommend_back_keyboard(),
                parse_mode="HTML",
            )
            return

        if action == "text":
            lang = get_user_language(user_id)
            current = get_bot_text("recommend_text", lang) or ""
            preview = html.escape(current) if current else "-"
            await cq.message.edit_text(
                "✏️ <b>Текст рекомендаций</b>\n\n"
                "Текущий текст:\n"
                f"<code>{preview}</code>\n\n"
                "Установить:\n"
                "<code>/admin recommend text Ваш текст</code>\n\n"
                "Очистить:\n"
                "<code>/admin recommend text clear</code>\n\n"
                "Поддерживается HTML: &lt;b&gt;, &lt;i&gt;, &lt;code&gt;, "
                "&lt;a href=\"...\"&gt;...&lt;/a&gt;",
                reply_markup=self._admin_recommend_back_keyboard(),
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            return

        if action == "help":
            await cq.message.edit_text(
                "📚 <b>Справка по управлению товарами</b>\n\n"
                "<b>Добавление:</b>\n"
                "<code>/admin recommend add \"Название\" \"URL\" [цена] [категория] [бренд]</code>\n\n"
                "<b>Удаление:</b>\n"
                "<code>/admin recommend remove ID</code>\n\n"
                "<b>Приоритет:</b>\n"
                "<code>/admin recommend priority ID число</code>\n\n"
                "<b>Текст:</b>\n"
                "<code>/admin recommend text ...</code>\n\n"
                "<b>Список:</b>\n"
                "<code>/admin recommend list</code>",
                reply_markup=self._admin_recommend_back_keyboard(),
                parse_mode="HTML",
            )
            return

        await cq.answer(self.t(user_id, "error_generic"), show_alert=True)

    async def _handle_admin_product_delete(self, cq: CallbackQuery, product_id: int):
        if remove_recommended_product(product_id):
            await cq.message.edit_text(
                f"🗑️ <b>Товар #{product_id} удалён</b>",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="📋 Список товаров", callback_data="admin_recommend_list")],
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_recommend")],
                ]),
                parse_mode="HTML",
            )
            return
        await cq.answer("Товар не найден", show_alert=True)

    async def _handle_admin_product_priority(self, cq: CallbackQuery, product_id: int):
        await cq.message.edit_text(
            "⭐ <b>Изменение приоритета</b>\n\n"
            "Используйте команду:\n"
            f"<code>/admin recommend priority {product_id} ПРИОРИТЕТ</code>\n\n"
            "Пример:\n"
            f"<code>/admin recommend priority {product_id} 10</code>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📋 Список товаров", callback_data="admin_recommend_list")],
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_recommend")],
            ]),
            parse_mode="HTML",
        )

    async def _handle_admin_product_details(self, cq: CallbackQuery, product_id: int):
        products = get_recommended_products()
        product = next((item for item in products if item["id"] == product_id), None)
        if not product:
            await cq.answer("Товар не найден", show_alert=True)
            return

        title = html.escape(str(product.get("title") or "Без названия"))
        price = html.escape(str(product.get("price") or "Не указана"))
        category = html.escape(str(product.get("category") or "Не указана"))
        brand = html.escape(str(product.get("brand") or "Не указан"))
        url = html.escape(str(product.get("url") or ""))
        reason = html.escape(str(product.get("reason_template") or "Рекомендуемый товар"))

        text = (
            f"📦 <b>{title}</b>\n\n"
            f"🆔 ID: <code>{product['id']}</code>\n"
            f"💰 Цена: {price}\n"
            f"🎯 Категория: {category}\n"
            f"🏷️ Бренд: {brand}\n"
            f"⭐ Приоритет: {product.get('priority', 0)}\n"
            f"🔗 Ссылка: {url[:80]}{'...' if len(url) > 80 else ''}\n\n"
            f"📝 {reason}"
        )

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🗑️ Удалить", callback_data=f"admin_product_delete_{product_id}"),
                InlineKeyboardButton(text="⭐ Приоритет", callback_data=f"admin_product_priority_{product_id}"),
            ],
            [
                InlineKeyboardButton(text="📋 К списку", callback_data="admin_recommend_list"),
                InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_recommend"),
            ],
        ])

        await cq.message.edit_text(
            text,
            reply_markup=keyboard,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

    @staticmethod
    def _short_admin_value(value, limit: int = 90) -> str:
        text = re.sub(r"\s+", " ", str(value or "").strip())
        if len(text) <= limit:
            return text
        return text[: max(0, limit - 3)].rstrip() + "..."

    @staticmethod
    def _format_admin_ts(ts_value) -> str:
        if not ts_value:
            return "-"
        try:
            return datetime.fromtimestamp(int(ts_value)).strftime("%d.%m.%Y %H:%M")
        except Exception:
            return "-"

    @staticmethod
    def _format_admin_price(price) -> str:
        if price is None:
            return "-"
        try:
            return f"{float(price):.0f} TL"
        except (TypeError, ValueError):
            return "-"

    def _admin_bad_subscription_keyboard(self, sub_id: int, *, confirm_delete: bool = False) -> InlineKeyboardMarkup:
        if confirm_delete:
            return InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Удалить", callback_data=f"admin_bad_delete_confirm:{sub_id}"),
                    InlineKeyboardButton(text="🚫 Отмена", callback_data=f"admin_bad_sub:{sub_id}"),
                ],
                [InlineKeyboardButton(text="⚠️ К списку", callback_data="admin_broken_subs")],
            ])

        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🔁 Проверить", callback_data=f"admin_bad_recheck:{sub_id}"),
                InlineKeyboardButton(text="⏸ Пауза", callback_data=f"admin_bad_pause:{sub_id}"),
            ],
            [
                InlineKeyboardButton(text="🗑 Удалить", callback_data=f"admin_bad_delete:{sub_id}"),
                InlineKeyboardButton(text="⚠️ К списку", callback_data="admin_broken_subs"),
            ],
        ])

    def _format_admin_bad_subscription_text(self, row, *, notice: str = "") -> str:
        sub_id = int(row.get("id") or 0)
        owner_id = int(row.get("user_id") or 0)
        title = self._short_admin_value(row.get("product_title") or row.get("url"), 120)
        url = self._short_admin_value(row.get("url"), 180)
        username = row.get("username")
        first_name = row.get("first_name")
        last_name = row.get("last_name")
        display_name = " ".join(part for part in [first_name, last_name] if part).strip()
        if username:
            user_text = f"{display_name} (@{username})" if display_name else f"@{username}"
        else:
            user_text = display_name or f"ID {owner_id}"
        fail_count = int(row.get("check_fail_count") or 0)
        last_error = self._short_admin_value(row.get("last_check_error") or "-", 120)
        last_error_at = self._format_admin_ts(row.get("last_check_error_at"))
        last_price = self._format_admin_price(row.get("last_price"))
        active = bool(int(row.get("is_active") if row.get("is_active") is not None else 1))
        status = "активна" if active else "на паузе"

        notice_block = f"{notice}\n\n" if notice else ""
        return (
            f"{notice_block}⚠️ <b>Проблемная подписка</b>\n\n"
            f"🆔 <b>Sub:</b> <code>{sub_id}</code>\n"
            f"👤 <b>User:</b> {_safe_html(user_text)} | <code>{owner_id}</code>\n"
            f"📌 <b>Статус:</b> {_safe_html(status)}\n"
            f"📦 <b>{_safe_html(title)}</b>\n"
            f"💰 <b>Last price:</b> {_safe_html(last_price)}\n"
            f"❌ <b>Failures:</b> <b>{fail_count}</b>\n"
            f"🧾 <b>Reason:</b> <code>{_safe_html(last_error)}</code>\n"
            f"🕒 <b>Last error:</b> {_safe_html(last_error_at)}\n\n"
            f"🔗 <code>{_safe_html(url)}</code>"
        )

    async def _handle_admin_bad_subscription_details(self, cq: CallbackQuery, sub_id: int, *, notice: str = "") -> None:
        row = get_subscription_failure_details(sub_id)
        if not row:
            await cq.answer("Подписка не найдена", show_alert=True)
            return
        await cq.message.edit_text(
            self._format_admin_bad_subscription_text(row, notice=notice),
            reply_markup=self._admin_bad_subscription_keyboard(sub_id),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

    async def _handle_admin_bad_subscription_recheck(self, cq: CallbackQuery, sub_id: int, admin_user_id: int) -> None:
        row = get_subscription_failure_details(sub_id)
        if not row:
            await cq.answer("Подписка не найдена", show_alert=True)
            return

        url = str(row.get("url") or "")
        await cq.answer("Проверяю...")
        try:
            price, title, image = await get_product_info_async(url)
        except Exception as exc:
            reason = f"admin_recheck_error:{type(exc).__name__}"
            record_subscription_check_failure(sub_id, reason)
            action_event("ADMIN", "bad subscription recheck failed", admin=admin_user_id, sub_id=sub_id, reason=reason)
            await self._handle_admin_bad_subscription_details(
                cq,
                sub_id,
                notice=f"❌ <b>Повторная проверка не прошла:</b> <code>{_safe_html(type(exc).__name__)}</code>",
            )
            return

        if price is None:
            record_subscription_check_failure(sub_id, "admin_recheck_price_not_found")
            action_event("ADMIN", "bad subscription recheck found no price", admin=admin_user_id, sub_id=sub_id)
            await self._handle_admin_bad_subscription_details(
                cq,
                sub_id,
                notice="❌ <b>Повторная проверка не нашла цену.</b>",
            )
            return

        if title or image:
            update_subscription_meta(sub_id, title, image)
        update_last_price(sub_id, float(price))
        try:
            add_price_point(sub_id, url, float(price), source="admin_recheck")
        except Exception:
            logger.debug("Could not save admin recheck price point for sub %s", sub_id, exc_info=True)
        clear_subscription_check_failure(sub_id)
        action_event("ADMIN", "bad subscription recovered", admin=admin_user_id, sub_id=sub_id, price=f"{float(price):.0f} TL")

        await cq.message.edit_text(
            "✅ <b>Повторная проверка успешна</b>\n\n"
            f"Sub: <code>{sub_id}</code>\n"
            f"Цена: <b>{float(price):.0f} TL</b>\n\n"
            "Ошибка проверки очищена.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⚠️ К списку", callback_data="admin_broken_subs")],
                [InlineKeyboardButton(text="🏠 Админ-панель", callback_data="admin_main_menu")],
            ]),
            parse_mode="HTML",
        )

    async def _handle_admin_bad_subscription_pause(self, cq: CallbackQuery, sub_id: int, admin_user_id: int) -> None:
        if not get_subscription_failure_details(sub_id):
            await cq.answer("Подписка не найдена", show_alert=True)
            return
        if not set_subscription_active(sub_id, False):
            await cq.answer(self.t(admin_user_id, "error_generic"), show_alert=True)
            return
        action_event("ADMIN", "paused bad subscription", admin=admin_user_id, sub_id=sub_id)
        await self._handle_admin_bad_subscription_details(
            cq,
            sub_id,
            notice="⏸ <b>Подписка поставлена на паузу.</b>",
        )

    async def _handle_admin_bad_subscription_delete_prompt(self, cq: CallbackQuery, sub_id: int) -> None:
        row = get_subscription_failure_details(sub_id)
        if not row:
            await cq.answer("Подписка не найдена", show_alert=True)
            return
        await cq.message.edit_text(
            self._format_admin_bad_subscription_text(
                row,
                notice="🗑 <b>Удалить эту подписку?</b>\nДействие нельзя отменить.",
            ),
            reply_markup=self._admin_bad_subscription_keyboard(sub_id, confirm_delete=True),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

    async def _handle_admin_bad_subscription_delete_confirm(self, cq: CallbackQuery, sub_id: int, admin_user_id: int) -> None:
        if not remove_subscription(sub_id):
            await cq.answer("Подписка не найдена", show_alert=True)
            return
        action_event("ADMIN", "deleted bad subscription", admin=admin_user_id, sub_id=sub_id)
        await cq.message.edit_text(
            f"🗑 <b>Подписка удалена</b>\n\nSub: <code>{sub_id}</code>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⚠️ К списку", callback_data="admin_broken_subs")],
                [InlineKeyboardButton(text="🏠 Админ-панель", callback_data="admin_main_menu")],
            ]),
            parse_mode="HTML",
        )

    async def _handle_admin_callback(self, cq: CallbackQuery, data: str, user_id: int) -> bool:
        if not await self._ensure_admin(cq, user_id):
            return True

        try:
            if data.startswith("admin_broadcast_confirm:"):
                await cq.answer(self.t(user_id, "loading"))
                from handlers.admin_handler import admin_broadcast_confirm

                token = data.split(":", 1)[1]
                await admin_broadcast_confirm(cq.message, user_id, token)
                return True

            if data.startswith("admin_broadcast_cancel:"):
                await cq.answer()
                from handlers.admin_handler import admin_broadcast_cancel

                token = data.split(":", 1)[1]
                await admin_broadcast_cancel(cq.message, user_id, token)
                return True

            if data.startswith("admin_cleanup_confirm:"):
                await cq.answer(self.t(user_id, "loading"))
                from handlers.admin_handler import admin_cleanup_confirm

                token = data.split(":", 1)[1]
                await admin_cleanup_confirm(cq.message, user_id, token)
                return True

            if data.startswith("admin_cleanup_cancel:"):
                await cq.answer()
                from handlers.admin_handler import admin_cleanup_cancel

                token = data.split(":", 1)[1]
                await admin_cleanup_cancel(cq.message, user_id, token)
                return True

            if data.startswith("admin_users_refresh"):
                await cq.answer(self.t(user_id, "loading"))
                from handlers.admin_handler import admin_users_list_interactive

                offset = 0
                if ":" in data:
                    try:
                        offset = int(data.split(":", 1)[1])
                    except ValueError:
                        offset = 0
                await admin_users_list_interactive(cq.message, offset=offset)
                return True

            if data.startswith("admin_users_page:"):
                await cq.answer(self.t(user_id, "loading"))
                from handlers.admin_handler import admin_users_list_interactive

                try:
                    offset = int(data.split(":", 1)[1])
                except ValueError:
                    offset = 0
                await admin_users_list_interactive(cq.message, offset=offset)
                return True

            if data == "admin_main_menu":
                await cq.answer()
                from handlers.admin_handler import admin_main_menu

                await admin_main_menu(cq.message)
                return True

            if data in {"admin_stats", "admin_stats_refresh"}:
                await cq.answer(self.t(user_id, "loading"))
                from handlers.admin_handler import admin_stats

                await admin_stats(cq.message)
                return True

            if data == "admin_users":
                await cq.answer(self.t(user_id, "loading"))
                from handlers.admin_handler import admin_users_list_interactive

                await admin_users_list_interactive(cq.message, offset=0)
                return True

            if data == "admin_check_blocked":
                await cq.answer(self.t(user_id, "loading"))
                from handlers.admin_handler import admin_check_blocked

                await admin_check_blocked(cq.message)
                return True

            if data == "admin_broken_subs":
                await cq.answer(self.t(user_id, "loading"))
                from handlers.admin_handler import admin_broken_subscriptions

                await admin_broken_subscriptions(cq.message)
                return True

            if data == "admin_health":
                await cq.answer(self.t(user_id, "loading"))
                from bot import cmd_health

                await cmd_health(cq.message)
                return True

            if data == "admin_premium":
                await cq.answer()
                from handlers.admin_handler import _admin_premium_back_keyboard, _admin_premium_help_text

                await cq.message.edit_text(
                    _admin_premium_help_text(),
                    reply_markup=_admin_premium_back_keyboard(),
                    parse_mode="HTML",
                )
                return True

            if data.startswith("admin_user_premium:"):
                await cq.answer()
                from handlers.admin_handler import admin_user_premium_menu

                target_user_id = int(data.split(":", 1)[1])
                await admin_user_premium_menu(cq.message, target_user_id)
                return True

            if data.startswith("admin_user_premium_grant:"):
                await cq.answer("Premium updated")
                from handlers.admin_handler import admin_user_premium_grant

                _prefix, target_text, days_text = data.split(":", 2)
                target_user_id = int(target_text)
                days = None if days_text == "forever" else int(days_text)
                await admin_user_premium_grant(cq.message, cq.from_user, target_user_id, days)
                return True

            if data.startswith("admin_user_premium_revoke:"):
                await cq.answer("Premium removed")
                from handlers.admin_handler import admin_user_premium_revoke

                target_user_id = int(data.split(":", 1)[1])
                await admin_user_premium_revoke(cq.message, cq.from_user, target_user_id)
                return True

            if data.startswith("admin_bad_sub:"):
                await cq.answer()
                sub_id = int(data.split(":", 1)[1])
                await self._handle_admin_bad_subscription_details(cq, sub_id)
                return True

            if data.startswith("admin_bad_recheck:"):
                sub_id = int(data.split(":", 1)[1])
                await self._handle_admin_bad_subscription_recheck(cq, sub_id, user_id)
                return True

            if data.startswith("admin_bad_pause:"):
                await cq.answer()
                sub_id = int(data.split(":", 1)[1])
                await self._handle_admin_bad_subscription_pause(cq, sub_id, user_id)
                return True

            if data.startswith("admin_bad_delete_confirm:"):
                await cq.answer()
                sub_id = int(data.split(":", 1)[1])
                await self._handle_admin_bad_subscription_delete_confirm(cq, sub_id, user_id)
                return True

            if data.startswith("admin_bad_delete:"):
                await cq.answer()
                sub_id = int(data.split(":", 1)[1])
                await self._handle_admin_bad_subscription_delete_prompt(cq, sub_id)
                return True

            if data == "admin_recommend":
                await cq.answer()
                await cq.message.edit_text(
                    "🎯 <b>Управление рекомендуемыми товарами</b>\n\n"
                    "Выберите действие или используйте команды:\n"
                    "<code>/admin recommend list</code> - список товаров\n"
                    "<code>/admin recommend add \"Название\" \"URL\"</code> - добавить\n"
                    "<code>/admin recommend remove ID</code> - удалить\n"
                    "<code>/admin recommend priority ID приоритет</code> - приоритет\n"
                    "<code>/admin recommend text ТЕКСТ</code> - текст кнопки рекомендаций",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
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
                        ],
                    ]),
                    parse_mode="HTML",
                )
                return True

            if data.startswith("admin_recommend_"):
                await cq.answer()
                action = data.replace("admin_recommend_", "", 1)
                await self._handle_admin_recommend_action(cq, action, user_id)
                return True

            if data.startswith("admin_product_delete_"):
                await cq.answer()
                product_id = int(data.replace("admin_product_delete_", "", 1))
                await self._handle_admin_product_delete(cq, product_id)
                return True

            if data.startswith("admin_product_priority_"):
                await cq.answer()
                product_id = int(data.replace("admin_product_priority_", "", 1))
                await self._handle_admin_product_priority(cq, product_id)
                return True

            if data.startswith("admin_product_"):
                await cq.answer()
                product_id = int(data.replace("admin_product_", "", 1))
                await self._handle_admin_product_details(cq, product_id)
                return True

            if data == "admin_broadcast_menu":
                await cq.answer()
                await cq.message.edit_text(
                    "📢 <b>Рассылка сообщений</b>\n\n"
                    "Используйте команду:\n"
                    "<code>/admin broadcast &lt;сообщение&gt;</code>\n\n"
                    "Пример:\n"
                    "<code>/admin broadcast Привет! У нас новинка в разделе рекомендаций!</code>\n\n"
                    "<b>⚠️ Внимание:</b> сообщение будет отправлено всем пользователям бота.",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="📢 Начать рассылку", callback_data="admin_broadcast_start")],
                        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_main_menu")],
                    ]),
                    parse_mode="HTML",
                )
                return True

            if data == "admin_broadcast_start":
                await cq.answer()
                await cq.message.edit_text(
                    "📢 <b>Рассылка сообщений</b>\n\n"
                    "Отправьте команду:\n"
                    "<code>/admin broadcast &lt;сообщение&gt;</code>\n\n"
                    "Пример:\n"
                    "<code>/admin broadcast Привет! У нас новинка в разделе рекомендаций!</code>\n\n"
                    "<b>⚠️ Внимание:</b> сообщение получат все пользователи бота.",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_main_menu")]
                    ]),
                    parse_mode="HTML",
                )
                return True

            if data == "admin_cleanup":
                await cq.answer()
                from handlers.admin_handler import admin_cleanup

                await admin_cleanup(cq.message)
                return True

            if data == "admin_backup":
                await cq.answer()
                from handlers.admin_handler import admin_backup

                await admin_backup(cq.message)
                return True

            if data == "admin_help":
                await cq.answer()
                await cq.message.edit_text(
                    "📚 <b>Справка по админ функциям</b>\n\n"
                    "🎯 <b>Рекомендации:</b>\n"
                    "- Добавляйте товары для рекламы\n"
                    "- Управляйте приоритетом показа\n"
                    "- Меняйте текст кнопки рекомендаций\n\n"
                    "👥 <b>Пользователи:</b>\n"
                    "- Просматривайте активность\n"
                    "- Проверяйте блокировки\n\n"
                    "📊 <b>Статистика:</b>\n"
                    "- Мониторьте использование\n"
                    "- Отслеживайте рост",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_main_menu")]
                    ]),
                    parse_mode="HTML",
                )
                return True

            return False
        except ValueError:
            await cq.answer(self.t(user_id, "error_invalid_id"), show_alert=True)
            return True
        except Exception as e:
            logger.exception("admin callback error for %s: %s", data, e)
            await self._send_callback_problem(cq, user_id)
            return True

    async def handle_admin_user_details(self, cq: CallbackQuery):
        """Handle admin user details callbacks."""
        try:

            from config import ADMIN_IDS
            if cq.from_user.id not in ADMIN_IDS:
                await cq.answer(self.t(cq.from_user.id, "admin_only"), show_alert=True)
                return


            target_user_id = int(cq.data.split(":", 1)[1])

            await cq.answer(self.t(cq.from_user.id, "loading_user_details"))


            try:
                from handlers.admin_handler import admin_user_details_callback
                await admin_user_details_callback(cq.message, target_user_id, cq.from_user.id)
            except Exception as e:
                logger.exception("admin_user_details_callback failed: %s", e)
                await cq.message.edit_text(self.t(cq.from_user.id, "error_generic"))

        except ValueError:
            await cq.answer(self.t(cq.from_user.id, "invalid_user_id"), show_alert=True)
        except Exception as e:
            logger.exception("Admin user details error: %s", e)
            await cq.answer(self.t(cq.from_user.id, "error_generic"), show_alert=True)

    def register(self, dp):
        """Register all callback handlers."""
        from aiogram import F


        dp.callback_query.register(
            self.handle_admin_user_details,
            F.data.startswith("user_details:")
        )


        dp.callback_query.register(self.handle_main_callback)












