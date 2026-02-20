"""
Handlers for callback queries (button clicks).
"""
from aiogram import types
from aiogram.types import CallbackQuery

from .base import BaseHandler
from database import (
    get_subscription, remove_subscription, remove_subscriptions_by_user,
    update_mode, set_user_language
)
from keyboards import subscription_controls_kb_for_user, get_main_kb
from localization import update_language_cache
import sqlite3
import logging

logger = logging.getLogger(__name__)


class CallbackHandler(BaseHandler):
    """Handler for callback queries from inline keyboards."""

    async def handle_main_callback(self, cq: CallbackQuery):
        """Handle main callback queries."""
        data = cq.data or ""
        user_id = cq.from_user.id
        logger.info(f"Callback received: data='{data}', user={user_id}")

        try:
            # --- Detailed help ---
            if data == "help:full":
                await cq.answer()
                await cq.message.edit_text(self.t(user_id, "help_full"))
                return

            # --- Language change ---
            if data.startswith("lang:"):
                await cq.answer()
                lang = data.split(":", 1)[1]
                set_user_language(user_id, lang)
                update_language_cache(user_id, lang)
                try:
                    await self.bot.send_message(
                        user_id,
                        self.t(user_id, "start_text"),
                        reply_markup=get_main_kb(user_id),
                        parse_mode="Markdown",
                    )
                    await cq.message.edit_text(self.t(user_id, "lang_changed"))
                except Exception as e:
                    logger.warning("Failed to update language UI for %s: %s", user_id, e)
                return

            # --- Single unsubscribe ---
            # --- Trending callbacks ---
            if data.startswith("trend:"):
                await cq.answer()
                try:
                    parts = data.split(":")
                    # trend:all
                    if len(parts) >= 2 and parts[1] == "all":
                        from scraper import get_trending_all_top3_async, get_trending_sample
                        import bot as _bot
                        items = await get_trending_all_top3_async()
                        if not items:
                            # fallback: show canned sample headlines instead of hard "no access" message
                            sample = get_trending_sample()
                            if sample:
                                await cq.message.edit_text(self.t(user_id, "trending_header") + "\n\n" + "\n\n".join(sample))
                            else:
                                await cq.message.edit_text(self.t(user_id, "trending_unavailable"))
                            return
                        header = self.t(user_id, "trending_header")
                        await self.bot.send_message(user_id, header + "\n\n" + _bot.format_trending_items(user_id, items))
                        return

                    # trend:catmenu
                    if len(parts) >= 2 and parts[1] == "catmenu":
                        import bot as _bot
                        kb = _bot.trending_categories_kb(user_id)
                        await cq.message.edit_text(self.t(user_id, "trending_choose_category"), reply_markup=kb)
                        return

                    # trend:search -> prompt user to enter query (state set in bot)
                    if len(parts) >= 2 and parts[1] == "search":
                        import bot as _bot
                        _bot.TREND_SEARCH_AWAIT.add(user_id)
                        await cq.message.edit_text(self.t(user_id, "trending_enter_query"))
                        return

                    # trend:cat:<key>
                    if len(parts) >= 3 and parts[1] == "cat":
                        cat_key = parts[2]
                        from scraper import get_trending_by_category_top3_async, get_trending_sample
                        import bot as _bot
                        items = await get_trending_by_category_top3_async(cat_key)
                        if not items:
                            sample = get_trending_sample()
                            if sample:
                                await cq.message.edit_text(self.t(user_id, "trending_header") + "\n\n" + "\n\n".join(sample))
                                return
                            await cq.message.edit_text(self.t(user_id, "trending_no_results"))
                            return
                        await self.bot.send_message(user_id, self.t(user_id, "trending_header") + "\n\n" + _bot.format_trending_items(user_id, items))
                        return

                except Exception as e:
                    logger.exception("Trending callback error: %s", e)
                    await cq.answer(self.t(user_id, "error_generic"), show_alert=True)
                return

            # --- Compare prices ---
            if data.startswith("compare:"):
                await cq.answer(self.t(user_id, "compare_loading"))
                try:
                    from scraper import get_comparison_report

                    sub_id = int(data.split(":", 1)[1])
                    sub = get_subscription(sub_id)
                    if not sub or sub[1] != user_id:
                        await self.bot.send_message(
                            user_id, self.t(user_id, "error_not_your_sub")
                        )
                        return

                    comparison = await get_comparison_report(user_id, sub_id)
                    if comparison:
                        await self.bot.send_message(
                            user_id, comparison, parse_mode="Markdown"
                        )
                    else:
                        await self.bot.send_message(
                            user_id, self.t(user_id, "compare_no_similar")
                        )

                except ValueError:
                    await cq.answer(self.t(user_id, "error_invalid_id"), show_alert=True)
                except Exception as e:
                    logger.exception("compare callback error: %s", e)
                    await self.bot.send_message(user_id, self.t(user_id, "error_generic"))
                return
            if data.startswith(("unsubscribe:", "delete:")):
                try:
                    sub_id = int(data.split(":", 1)[1])
                    sub = get_subscription(sub_id)
                    if sub and sub[1] == user_id:
                        remove_subscription(sub_id)
                        await cq.message.edit_text(self.t(user_id, "sub_removed"))
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

            # --- Confirm mass unsubscribe ---
            if data.startswith("confirm_unsub_all:"):
                await cq.answer()
                try:
                    ans = data.split(":", 1)[1]
                    if ans == "yes":
                        remove_subscriptions_by_user(user_id)
                        await cq.message.edit_text(self.t(user_id, "unsubscribed_all"))
                    else:
                        await cq.message.edit_text(self.t(user_id, "action_cancelled"))
                except Exception as e:
                    logger.exception("Mass unsubscribe error: %s", e)
                    await cq.message.edit_text(self.t(user_id, "error_generic"))
                return

            # --- Mode change ---
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

                        # Check ownership
                        owner_ok = len(sub) >= 2 and sub[1] == user_id
                        if not owner_ok:
                            await cq.answer(self.t(user_id, "error_not_your_sub"), show_alert=True)
                            return

                        try:
                            update_mode(sub_id, mode)
                        except Exception as e:
                            logger.exception("Update mode error for sub %s: %s", sub_id, e)
                            await cq.answer(self.t(user_id, "error_generic"), show_alert=True)
                            return

                        # Update UI
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

            # --- Edit subscription ---
            if data.startswith("edit_sub:"):
                await cq.answer()
                try:
                    sub_id = int(data.split(":", 1)[1])
                    sub = get_subscription(sub_id)
                    if not sub or sub[1] != user_id:
                        await cq.answer(self.t(user_id, "error_not_your_sub"), show_alert=True)
                        return

                    # Extract subscription data
                    try:
                        (_, _, url, mode, last_price, product_title, product_image,
                         min_price, max_price, notify_percent, notify_interval, last_notify_time, price_alert) = sub
                    except ValueError:
                        (_, _, url, mode, last_price, product_title, product_image,
                         min_price, max_price, notify_percent, notify_interval, last_notify_time) = sub[:12]
                        price_alert = None

                    # Format subscription info
                    title = product_title if product_title else url[:60] + "..." if len(url) > 60 else url
                    price_text = f"{last_price:.0f} TL" if last_price is not None else self.t(user_id, "unknown_price")
                    mode_text = self.t(user_id, "mode_hourly") if mode == "hourly" else self.t(user_id, "mode_discount")

                    edit_text = f"⚙️ *{self.t(user_id, 'edit_subscription')}*\n\n"
                    edit_text += f"📦 {title}\n"
                    edit_text += f"🔗 {url[:50]}...\n\n"
                    edit_text += f"💰 {self.t(user_id, 'current_price')}: {price_text}\n"
                    edit_text += f"🔔 {self.t(user_id, 'mode')}: {mode_text}\n"

                    if price_alert is not None:
                        edit_text += f"🎯 {self.t(user_id, 'price_alert_label')}: {price_alert:.0f} TL\n"
                    if min_price is not None:
                        edit_text += f"📉 {self.t(user_id, 'min_price_label')}: {min_price:.0f} TL\n"
                    if max_price is not None:
                        edit_text += f"📈 {self.t(user_id, 'max_price_label')}: {max_price:.0f} TL\n"
                    if notify_percent is not None:
                        edit_text += f"📊 {self.t(user_id, 'notify_percent')}: {notify_percent:.1f}%\n"
                    if notify_interval is not None and notify_interval != 60:
                        edit_text += f"⏰ {self.t(user_id, 'interval')}: {notify_interval} {self.t(user_id, 'minutes')}\n"

                    # Send edit message
                    await self.bot.send_message(
                        user_id,
                        edit_text,
                        reply_markup=subscription_controls_kb_for_user(user_id, sub_id),
                        parse_mode="Markdown"
                    )

                except ValueError:
                    await cq.answer(self.t(user_id, "error_invalid_id"), show_alert=True)
                except Exception as e:
                    logger.exception("Edit subscription error: %s", e)
                    await cq.answer(self.t(user_id, "error_generic"), show_alert=True)
                return

            # Unknown callback
            await cq.answer(self.t(user_id, "error_generic"), show_alert=True)

        except Exception as e:
            logger.exception("Main callback handler error: %s", e)
            await cq.answer(self.t(user_id, "error_generic"), show_alert=True)

    async def handle_admin_user_details(self, cq: CallbackQuery):
        """Handle admin user details callbacks."""
        try:
            # Check admin permissions
            from config import ADMIN_IDS
            if cq.from_user.id not in ADMIN_IDS:
                await cq.answer(self.t(cq.from_user.id, "admin_only"), show_alert=True)
                return

            # Extract user ID
            target_user_id = int(cq.data.split(":", 1)[1])

            await cq.answer(self.t(cq.from_user.id, "loading_user_details"))

            # Delegate to main admin details implementation in bot.py
            try:
                from bot import admin_user_details_callback
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
        
        # Register admin user details handler first (more specific)
        dp.callback_query.register(
            self.handle_admin_user_details,
            F.data.startswith("user_details:")
        )
        
        # Register main callback handler (catchall for other callbacks)
        dp.callback_query.register(self.handle_main_callback)












