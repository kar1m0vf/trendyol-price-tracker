"""
Handlers for callback queries (button clicks).
"""
from datetime import datetime

from aiogram import types
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
import html
import re

from .base import BaseHandler
from database import (
    get_subscription, remove_subscription, remove_subscriptions_by_user,
    update_mode, set_user_language, update_subscription_settings,
    get_price_history, add_price_point, get_user_subscriptions,
    get_user_language, get_bot_text, get_recommended_products,
    remove_recommended_product
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

            if data == "help:full":
                await cq.answer()
                await cq.message.edit_text(self.t(user_id, "help_full"))
                return


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



            if data.startswith("trend:"):
                await cq.answer()
                status_message = None
                try:
                    parts = data.split(":")

                    if len(parts) >= 2 and parts[1] == "all":
                        from scraper import get_trending_all_top3_async, get_trending_sample
                        import bot as _bot
                        status_message = await self.send_status_message(
                            user_id,
                            self.t(user_id, "status_loading_trends"),
                        )
                        items = await get_trending_all_top3_async()
                        if not items:

                            sample = get_trending_sample()
                            if sample:
                                await self.replace_status_message(
                                    status_message,
                                    self.t(user_id, "trending_header") + "\n\n" + "\n\n".join(sample),
                                    fallback_target=user_id,
                                )
                            else:
                                await self.replace_status_message(
                                    status_message,
                                    self.t(user_id, "trending_unavailable"),
                                    fallback_target=user_id,
                                )
                            return
                        header = self.t(user_id, "trending_header")
                        await self.replace_status_message(
                            status_message,
                            header + "\n\n" + _bot.format_trending_items(user_id, items),
                            fallback_target=user_id,
                        )
                        return


                    if len(parts) >= 2 and parts[1] == "catmenu":
                        import bot as _bot
                        kb = _bot.trending_categories_kb(user_id)
                        await cq.message.edit_text(self.t(user_id, "trending_choose_category"), reply_markup=kb)
                        return


                    if len(parts) >= 2 and parts[1] == "search":
                        import bot as _bot
                        _bot.TREND_SEARCH_AWAIT.add(user_id)
                        await cq.message.edit_text(self.t(user_id, "trending_enter_query"))
                        return


                    if len(parts) >= 3 and parts[1] == "cat":
                        cat_key = parts[2]
                        from scraper import get_trending_by_category_top3_async, get_trending_sample
                        import bot as _bot
                        status_message = await self.send_status_message(
                            user_id,
                            self.t(user_id, "status_loading_trends"),
                        )
                        items = await get_trending_by_category_top3_async(cat_key)
                        if not items:
                            sample = get_trending_sample()
                            if sample:
                                await self.replace_status_message(
                                    status_message,
                                    self.t(user_id, "trending_header") + "\n\n" + "\n\n".join(sample),
                                    fallback_target=user_id,
                                )
                                return
                            await self.replace_status_message(
                                status_message,
                                self.t(user_id, "trending_no_results"),
                                fallback_target=user_id,
                            )
                            return
                        await self.replace_status_message(
                            status_message,
                            self.t(user_id, "trending_header") + "\n\n" + _bot.format_trending_items(user_id, items),
                            fallback_target=user_id,
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


            if data.startswith("compare:"):
                await cq.answer(self.t(user_id, "status_loading_compare"))
                status_message = await self.send_status_message(
                    user_id,
                    self.t(user_id, "status_loading_compare"),
                )
                try:
                    from scraper import get_comparison_report

                    sub_id = int(data.split(":", 1)[1])
                    sub = get_subscription(sub_id)
                    if not sub or sub[1] != user_id:
                        await self.replace_status_message(
                            status_message,
                            self.t(user_id, "error_not_your_sub"),
                            fallback_target=user_id,
                        )
                        return

                    comparison = await get_comparison_report(user_id, sub_id)
                    if comparison:
                        await self.replace_status_message(
                            status_message,
                            comparison,
                            fallback_target=user_id,
                            parse_mode="Markdown",
                        )
                    else:
                        await self.replace_status_message(
                            status_message,
                            self.t(user_id, "compare_no_similar"),
                            fallback_target=user_id,
                        )

                except ValueError:
                    await self.replace_status_message(
                        status_message,
                        self.t(user_id, "error_invalid_id"),
                        fallback_target=user_id,
                    )
                except Exception as e:
                    logger.exception("compare callback error: %s", e)
                    await self.replace_status_message(
                        status_message,
                        self.t(user_id, "error_generic"),
                        fallback_target=user_id,
                    )
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
                await cq.answer()
                try:
                    from bot import format_subscription_card

                    sub_id = int(data.split(":", 1)[1])
                    sub = get_subscription(sub_id)
                    if not sub or sub[1] != user_id:
                        await cq.answer(self.t(user_id, "error_not_your_sub"), show_alert=True)
                        return


                    try:
                        (_, _, url, mode, last_price, product_title, product_image,
                         min_price, max_price, notify_percent, notify_interval, last_notify_time, price_alert) = sub
                    except ValueError:
                        (_, _, url, mode, last_price, product_title, product_image,
                         min_price, max_price, notify_percent, notify_interval, last_notify_time) = sub[:12]
                        price_alert = None

                    edit_text = (
                        f"⚙️ <b>{html.escape(self.t(user_id, 'edit_subscription'))}</b>\n\n"
                        + format_subscription_card(user_id, sub)
                    )


                    await self.bot.send_message(
                        user_id,
                        edit_text,
                        reply_markup=subscription_controls_kb_for_user(user_id, sub_id),
                        parse_mode="HTML",
                        disable_web_page_preview=True,
                    )

                except ValueError:
                    await cq.answer(self.t(user_id, "error_invalid_id"), show_alert=True)
                except Exception as e:
                    logger.exception("Edit subscription error: %s", e)
                    await cq.answer(self.t(user_id, "error_generic"), show_alert=True)
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
            await cq.answer(self.t(user_id, "error_generic"), show_alert=True)

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
                f"{html.escape(self.t(user_id, 'alerts_edit_help'))}"
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

            from bot import alert_edit_state
            alert_edit_state[user_id] = sub_id
        except Exception as e:
            logger.exception("alert_edit callback error: %s", e)
            await cq.answer(self.t(user_id, "error_generic"), show_alert=True)

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
            await cq.answer(self.t(user_id, "error_generic"), show_alert=True)

    async def _show_alerts_list(self, cq: CallbackQuery, user_id: int):
        try:
            subs = get_user_subscriptions(user_id)
            if not subs:
                await cq.message.edit_text(self.t(user_id, "no_subs"))
                return

            lines = [self.t(user_id, "alerts_header")]
            keyboard = []

            for sub in subs:
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
                        text=f"⚙️ {self.t(user_id, 'btn_edit')} ID {sub_id}",
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
            await cq.answer(self.t(user_id, "error_generic"), show_alert=True)

    async def _send_history_plot(self, user_id: int, url: str, hist):
        from services.notification_service import NotificationService

        service = NotificationService(self.bot)
        await service.send_history_plot(user_id, url, hist)

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
                await self._send_history_plot(user_id, url, hist)
                await self.clear_status_message(status_message)
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

            await self._send_history_plot(user_id, url, hist)
            await self.clear_status_message(status_message)
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

    async def _handle_admin_callback(self, cq: CallbackQuery, data: str, user_id: int) -> bool:
        if not await self._ensure_admin(cq, user_id):
            return True

        try:
            if data == "admin_users_refresh":
                await cq.answer(self.t(user_id, "loading"))
                from handlers.admin_handler import admin_users_list_interactive

                await admin_users_list_interactive(cq.message)
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

                await admin_users_list_interactive(cq.message)
                return True

            if data == "admin_check_blocked":
                await cq.answer(self.t(user_id, "loading"))
                from handlers.admin_handler import admin_check_blocked

                await admin_check_blocked(cq.message)
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
            await cq.answer(self.t(user_id, "error_generic"), show_alert=True)
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












