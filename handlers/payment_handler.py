"""Telegram Stars payment handlers."""

from __future__ import annotations

from datetime import datetime
import logging
from typing import Any, Optional

from aiogram import types

from config import ADMIN_IDS, PREMIUM_MAX_SUBSCRIPTIONS_PER_USER, TELEGRAM_STARS_CURRENCY
import database
from services.payment_service import PaymentKind, PaymentStatus, apply_successful_payment, get_payment_plan

from .base import BaseHandler


logger = logging.getLogger(__name__)

PAYMENT_PAYLOAD_PREFIX = "payment_event:"


def build_payment_payload(event_id: int) -> str:
    return f"{PAYMENT_PAYLOAD_PREFIX}{int(event_id)}"


def parse_payment_payload(payload: Any) -> Optional[int]:
    if not isinstance(payload, str):
        return None
    if not payload.startswith(PAYMENT_PAYLOAD_PREFIX):
        return None
    raw_event_id = payload[len(PAYMENT_PAYLOAD_PREFIX):].strip()
    if not raw_event_id.isdigit():
        return None
    event_id = int(raw_event_id)
    return event_id if event_id > 0 else None


def _format_access_date(ts: int) -> str:
    return datetime.fromtimestamp(int(ts)).strftime("%d.%m.%Y")


def _successful_payment_payload(successful_payment: Any) -> dict:
    return {
        "currency": getattr(successful_payment, "currency", None),
        "total_amount": getattr(successful_payment, "total_amount", None),
        "invoice_payload": getattr(successful_payment, "invoice_payload", None),
        "telegram_payment_charge_id": getattr(successful_payment, "telegram_payment_charge_id", None),
        "provider_payment_charge_id": getattr(successful_payment, "provider_payment_charge_id", None),
    }


def _short_payment_value(value: Any, limit: int = 120) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


class PaymentHandler(BaseHandler):
    """Handle Telegram payment lifecycle events."""

    @staticmethod
    def _has_successful_payment(message: types.Message) -> bool:
        return getattr(message, "successful_payment", None) is not None

    async def _notify_admins_about_payment(self, message: types.Message, result) -> None:
        if not ADMIN_IDS:
            return
        bot = getattr(message, "bot", None)
        if bot is None:
            logger.debug("Payment admin notice skipped; message has no bot reference")
            return

        event = result.event
        for admin_id in ADMIN_IDS:
            try:
                text = self.t(
                    admin_id,
                    "admin_payment_received_notice",
                    event_id=int(event["id"]),
                    user_id=int(event["user_id"]),
                    plan=_short_payment_value(result.plan.id),
                    kind=_short_payment_value(result.plan.kind.value),
                    amount=event.get("amount") or "-",
                    currency=event.get("currency") or "-",
                    applied=self.t(
                        admin_id,
                        "admin_payment_applied_yes"
                        if result.applied or result.already_applied
                        else "admin_payment_applied_no",
                    ),
                )
                await bot.send_message(admin_id, text, parse_mode="HTML")
            except Exception:
                logger.debug("Could not send payment notice to admin=%s", admin_id, exc_info=True)

    async def handle_pre_checkout_query(self, query: types.PreCheckoutQuery) -> None:
        user_id = int(query.from_user.id)
        payload = getattr(query, "invoice_payload", None)
        event_id = parse_payment_payload(payload)
        if event_id is None:
            await query.answer(ok=False, error_message=self.t(user_id, "payment_invalid_payload"))
            return

        event = database.get_payment_event(event_id)
        if event is None or int(event["user_id"]) != user_id:
            await query.answer(ok=False, error_message=self.t(user_id, "payment_invalid_payload"))
            return

        if event.get("status") != PaymentStatus.PENDING.value:
            await query.answer(ok=False, error_message=self.t(user_id, "payment_not_pending"))
            return

        try:
            plan = get_payment_plan(event["plan_id"])
        except ValueError:
            logger.warning("Pre-checkout has unknown payment plan | event_id=%s", event_id)
            await query.answer(ok=False, error_message=self.t(user_id, "payment_invalid_payload"))
            return

        expected_amount = int(plan.amount or 0)
        expected_currency = plan.currency or TELEGRAM_STARS_CURRENCY
        actual_amount = int(getattr(query, "total_amount", 0) or 0)
        actual_currency = str(getattr(query, "currency", "") or "")
        if actual_amount != expected_amount or actual_currency != expected_currency:
            logger.warning(
                "Pre-checkout amount mismatch | event_id=%s user=%s expected=%s %s actual=%s %s",
                event_id,
                user_id,
                expected_amount,
                expected_currency,
                actual_amount,
                actual_currency,
            )
            await query.answer(ok=False, error_message=self.t(user_id, "payment_amount_mismatch"))
            return

        await query.answer(ok=True)

    async def handle_successful_payment(self, message: types.Message) -> None:
        user_id = int(message.from_user.id)
        successful_payment = getattr(message, "successful_payment", None)
        event_id = parse_payment_payload(getattr(successful_payment, "invoice_payload", None))
        if event_id is None:
            logger.warning("Successful payment without valid payload | user=%s", user_id)
            await message.answer(self.t(user_id, "payment_apply_failed"), parse_mode="HTML")
            return

        event = database.get_payment_event(event_id)
        if event is None or int(event["user_id"]) != user_id:
            logger.warning(
                "Successful payment event mismatch | message_user=%s event_id=%s",
                user_id,
                event_id,
            )
            await message.answer(self.t(user_id, "payment_apply_failed"), parse_mode="HTML")
            return

        try:
            plan = get_payment_plan(event["plan_id"])
        except ValueError:
            logger.warning("Successful payment has unknown payment plan | event_id=%s", event_id)
            await message.answer(self.t(user_id, "payment_apply_failed"), parse_mode="HTML")
            return

        actual_amount = int(getattr(successful_payment, "total_amount", 0) or 0)
        actual_currency = str(getattr(successful_payment, "currency", "") or "")
        expected_amount = int(plan.amount or 0)
        expected_currency = plan.currency or TELEGRAM_STARS_CURRENCY
        if actual_amount != expected_amount or actual_currency != expected_currency:
            logger.error(
                "Successful payment amount mismatch | event_id=%s user=%s expected=%s %s actual=%s %s",
                event_id,
                user_id,
                expected_amount,
                expected_currency,
                actual_amount,
                actual_currency,
            )
            await message.answer(self.t(user_id, "payment_apply_failed"), parse_mode="HTML")
            return

        charge_id = getattr(successful_payment, "telegram_payment_charge_id", None)
        try:
            result = apply_successful_payment(
                event_id,
                provider_payment_id=charge_id,
                payload=_successful_payment_payload(successful_payment),
            )
        except Exception:
            logger.exception("Failed to apply successful payment | user=%s event_id=%s", user_id, event_id)
            await message.answer(self.t(user_id, "payment_apply_failed"), parse_mode="HTML")
            return

        if result.plan.kind == PaymentKind.PREMIUM:
            if result.premium_until:
                text = self.t(
                    user_id,
                    "premium_payment_success_until",
                    date=_format_access_date(result.premium_until),
                    limit=PREMIUM_MAX_SUBSCRIPTIONS_PER_USER,
                )
            else:
                text = self.t(
                    user_id,
                    "premium_admin_granted_forever",
                    limit=PREMIUM_MAX_SUBSCRIPTIONS_PER_USER,
                )
        else:
            text = self.t(user_id, "donation_payment_success")

        await self._notify_admins_about_payment(message, result)
        await message.answer(text, parse_mode="HTML")

    def register(self, dp) -> None:
        dp.pre_checkout_query.register(self.handle_pre_checkout_query)
        dp.message.register(self.handle_successful_payment, self._has_successful_payment)
