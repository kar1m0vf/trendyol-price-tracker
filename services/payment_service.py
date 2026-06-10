"""Internal payment planning and application service.

This module does not create real Telegram invoices yet. It defines the stable
payment model that future Telegram Stars handlers can call into.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import time
from typing import Any, Dict, List, Optional

from access_control import get_effective_user_access
import database


class PaymentStatus(str, Enum):
    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"
    REFUNDED = "refunded"


class PaymentKind(str, Enum):
    PREMIUM = "premium"
    DONATION = "donation"


@dataclass(frozen=True)
class PaymentPlan:
    id: str
    kind: PaymentKind
    title: str
    duration_days: Optional[int] = None
    amount: Optional[int] = None
    currency: Optional[str] = None


@dataclass(frozen=True)
class PaymentApplicationResult:
    event: Dict[str, Any]
    plan: PaymentPlan
    applied: bool
    already_applied: bool = False
    premium_until: Optional[int] = None


PAYMENT_PLANS: Dict[str, PaymentPlan] = {
    "premium_30": PaymentPlan(
        id="premium_30",
        kind=PaymentKind.PREMIUM,
        title="Premium 30 days",
        duration_days=30,
    ),
    "premium_90": PaymentPlan(
        id="premium_90",
        kind=PaymentKind.PREMIUM,
        title="Premium 90 days",
        duration_days=90,
    ),
    "premium_365": PaymentPlan(
        id="premium_365",
        kind=PaymentKind.PREMIUM,
        title="Premium 365 days",
        duration_days=365,
    ),
    "donation": PaymentPlan(
        id="donation",
        kind=PaymentKind.DONATION,
        title="Donation",
    ),
}


def get_payment_plan(plan_id: str) -> PaymentPlan:
    try:
        return PAYMENT_PLANS[str(plan_id)]
    except KeyError as exc:
        raise ValueError(f"Unknown payment plan: {plan_id}") from exc


def list_payment_plans(kind: Optional[PaymentKind | str] = None) -> List[PaymentPlan]:
    if kind is None:
        return list(PAYMENT_PLANS.values())
    normalized = kind if isinstance(kind, PaymentKind) else PaymentKind(str(kind))
    return [plan for plan in PAYMENT_PLANS.values() if plan.kind == normalized]


def premium_plan_id_for_days(days: int) -> str:
    safe_days = int(days)
    plan_id = f"premium_{safe_days}"
    plan = get_payment_plan(plan_id)
    if plan.kind != PaymentKind.PREMIUM:
        raise ValueError(f"Plan is not a premium plan: {plan_id}")
    return plan_id


def create_pending_payment_event(
    user_id: int,
    plan_id: str,
    *,
    provider: str = "telegram_stars",
    payload: Optional[Any] = None,
    ts: Optional[int] = None,
) -> Dict[str, Any]:
    plan = get_payment_plan(plan_id)
    return database.create_payment_event(
        user_id,
        plan_id=plan.id,
        kind=plan.kind.value,
        status=PaymentStatus.PENDING.value,
        provider=provider,
        amount=plan.amount,
        currency=plan.currency,
        premium_days=plan.duration_days,
        payload=payload,
        ts=ts,
    )


def _premium_until_after_paid_plan(user_id: int, duration_days: int, now_ts: int) -> Optional[int]:
    access = get_effective_user_access(user_id, now=now_ts)
    if access["is_premium"] and access.get("premium_until") is None:
        return None

    base_ts = now_ts
    if access["is_premium"] and access.get("premium_until"):
        base_ts = max(now_ts, int(access["premium_until"]))
    return base_ts + int(duration_days) * 86400


def apply_successful_payment(
    event_id: int,
    *,
    provider_payment_id: Optional[str] = None,
    payload: Optional[Any] = None,
    ts: Optional[int] = None,
) -> PaymentApplicationResult:
    """Mark a payment as paid and apply its product effect exactly once."""
    now_ts = int(ts or time.time())
    event = database.get_payment_event(event_id)
    if event is None:
        raise ValueError(f"Payment event {event_id} not found")

    plan = get_payment_plan(event["plan_id"])
    if event.get("applied_at"):
        return PaymentApplicationResult(
            event=event,
            plan=plan,
            applied=False,
            already_applied=True,
        )

    if event.get("status") != PaymentStatus.PAID.value:
        event = database.mark_payment_event_paid(
            event_id,
            provider_payment_id=provider_payment_id,
            payload=payload,
            ts=now_ts,
        )
    elif provider_payment_id or payload is not None:
        event = database.update_payment_event_status(
            event_id,
            PaymentStatus.PAID.value,
            provider_payment_id=provider_payment_id,
            payload=payload,
            paid_at=event.get("paid_at") or now_ts,
            ts=now_ts,
        )

    premium_until = None
    if plan.kind == PaymentKind.PREMIUM:
        if not plan.duration_days:
            raise ValueError(f"Premium plan has no duration: {plan.id}")
        premium_until = _premium_until_after_paid_plan(
            int(event["user_id"]),
            int(plan.duration_days),
            now_ts,
        )
        database.grant_user_premium(int(event["user_id"]), premium_until=premium_until)

    event = database.mark_payment_event_applied(event_id, ts=now_ts)
    return PaymentApplicationResult(
        event=event,
        plan=plan,
        applied=True,
        premium_until=premium_until,
    )
