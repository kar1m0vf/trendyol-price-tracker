"""
Handlers for analytics and statistics commands.
"""
from typing import List, Tuple
from aiogram import types
from aiogram.filters import Command

from .base import BaseHandler
from database import (
    get_price_stats, get_user_subscriptions, get_subscription,
    get_top_price_drops, export_user_subscriptions
)
from datetime import datetime
import os


class AnalyticsHandler(BaseHandler):
    """Handler for analytics and statistics commands."""

    async def handle_stats_command(self, message: types.Message):
        """Handle /stats command - show price statistics for a subscription."""
        try:
            args = message.text.split()
            if len(args) < 2:
                await message.answer(self.t(message.from_user.id, "cmd_stats_usage"))
                return

            sub_id = int(args[1])
            sub = get_subscription(sub_id)

            if not sub:
                await message.answer(self.t(message.from_user.id, "no_subs_found_id"))
                return

                             
            if sub[1] != message.from_user.id:
                await message.answer(self.t(message.from_user.id, "error_not_your_sub"))
                return

            stats = get_price_stats(sub_id)

            if stats['count'] == 0:
                await message.answer(self.t(message.from_user.id, "stats_no_history"))
                return

                               
            curr = f"{stats['current']:.2f}" if stats['current'] else "—"
            min_p = f"{stats['min']:.2f}" if stats['min'] else "—"
            max_p = f"{stats['max']:.2f}" if stats['max'] else "—"
            avg_p = f"{stats['avg']:.2f}" if stats['avg'] else "—"

                                  
            header = self.t(message.from_user.id, "stats_header")
            text = f"""{header}

🏷️ ID: {sub_id}
🔗 {sub[2][:50]}...

💰 {self.t(message.from_user.id, 'current_price')}: {curr} TL
📉 {self.t(message.from_user.id, 'min_price')}: {min_p} TL
📈 {self.t(message.from_user.id, 'max_price')}: {max_p} TL
📊 {self.t(message.from_user.id, 'avg_price')}: {avg_p} TL
📈 {self.t(message.from_user.id, 'trend')}: {stats['trend']}
📅 {self.t(message.from_user.id, 'days_data')}: {stats['days']}
📌 {self.t(message.from_user.id, 'points')}: {stats['count']}
"""
            await message.answer(text, parse_mode="Markdown")

        except ValueError:
            await message.answer(self.t(message.from_user.id, "cmd_stats_usage"))
        except Exception as e:
            print(f"Stats command error: {e}")
            await message.answer(self.t(message.from_user.id, "error_generic"))

    async def handle_all_list_command(self, message: types.Message):
        """Handle /all_list command - show all subscriptions in table format."""
        try:
            subs = get_user_subscriptions(message.from_user.id)

            if not subs:
                await message.answer(self.t(message.from_user.id, "no_subs"))
                return

                             
            header = self.t(message.from_user.id, "cmd_all_list_header") + "\n\n"
            header += f"`ID  | {self.t(message.from_user.id, 'mode'):8} | {self.t(message.from_user.id, 'price'):6} | {self.t(message.from_user.id, 'status')}`\n"
            header += "`" + "—" * 38 + "`\n"

            rows = []
            for sub in subs:
                try:
                    (sub_id, user_id, url, mode, last_price, product_title, product_image,
                     min_price, max_price, notify_percent, notify_interval, last_notify_time, price_alert) = sub
                except ValueError:
                    (sub_id, user_id, url, mode, last_price, product_title, product_image,
                     min_price, max_price, notify_percent, notify_interval, last_notify_time) = sub[:12]
                    price_alert = None

                mode_short = "⏰" if mode == "hourly" else "💸" if mode == "discount" else "❓"
                price_str = f"{last_price:.0f}" if last_price else "—"
                alert_status = "🎯" if price_alert else " "

                row = f"`{sub_id:3d} | {mode_short} {mode:8s} | {price_str:6s} | {alert_status}`"
                rows.append(row)

            text = header + "\n".join(rows)
            text += f"\n\n✅ {self.t(message.from_user.id, 'total')}: {len(subs)} {self.t(message.from_user.id, 'subscriptions')}"

            await message.answer(text, parse_mode="Markdown")

        except Exception as e:
            print(f"All list command error: {e}")
            await message.answer(self.t(message.from_user.id, "error_generic"))

    async def handle_top_drops_command(self, message: types.Message):
        """Handle /top_drops command - show top products with biggest price drops."""
        try:
            drops = get_top_price_drops(message.from_user.id, limit=10)

            if not drops:
                await message.answer(self.t(message.from_user.id, "top_drops_no_data"))
                return

            text = self.t(message.from_user.id, "cmd_top_drops_header") + "\n\n"

            for i, (sub_id, url, title, curr_price, min_price, drop_pct) in enumerate(drops, 1):
                title_short = (title or self.t(message.from_user.id, "product"))[:30]
                icon = "🔴" if drop_pct < 0 else "🟢"
                curr_str = f"{curr_price:.0f}" if curr_price else "—"
                min_str = f"{min_price:.0f}" if min_price else "—"

                text += f"{i}. {icon} *{drop_pct:+.1f}%* | ID:{sub_id}\n"
                text += f"   {title_short}\n"
                text += f"   {self.t(message.from_user.id, 'current_price')}: {curr_str} TL | {self.t(message.from_user.id, 'min_price_label')}: {min_str} TL\n\n"

            await message.answer(text, parse_mode="Markdown")

        except Exception as e:
            print(f"Top drops command error: {e}")
            await message.answer(self.t(message.from_user.id, "error_generic"))

    def register(self, dp):
        """Register all analytics handlers."""
        dp.message.register(self.handle_stats_command, Command("stats"))
        dp.message.register(self.handle_all_list_command, Command("all_list"))
        dp.message.register(self.handle_top_drops_command, Command("top_drops"))












