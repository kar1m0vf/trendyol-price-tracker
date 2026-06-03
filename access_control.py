"""Internal bot access tiers and limits."""

import time
from typing import Any, Dict, Optional

from config import ADMIN_IDS, MAX_SUBSCRIPTIONS_PER_USER, PREMIUM_MAX_SUBSCRIPTIONS_PER_USER
from database import get_user_access


FREE_TIER = "free"
PREMIUM_TIER = "premium"


def get_effective_user_access(user_id: int, *, now: Optional[int] = None) -> Dict[str, Any]:
    """Return internal access state with expired premium resolved to free."""
    access = get_user_access(user_id)
    current_ts = int(time.time()) if now is None else int(now)
    raw_tier = str(access.get("access_tier") or FREE_TIER).lower()
    premium_until = access.get("premium_until")

    try:
        premium_until = int(premium_until) if premium_until else None
    except (TypeError, ValueError):
        premium_until = None

    is_active_premium = raw_tier == PREMIUM_TIER and (
        premium_until is None or premium_until > current_ts
    )
    effective_tier = PREMIUM_TIER if is_active_premium else FREE_TIER

    return {
        "access_tier": raw_tier if raw_tier in {FREE_TIER, PREMIUM_TIER} else FREE_TIER,
        "effective_tier": effective_tier,
        "is_premium": is_active_premium,
        "is_expired": raw_tier == PREMIUM_TIER and premium_until is not None and premium_until <= current_ts,
        "premium_until": premium_until,
    }


def get_subscription_limit_for_user(user_id: int) -> Optional[int]:
    """Return product limit for user; admins have no product limit."""
    if int(user_id) in ADMIN_IDS:
        return None
    access = get_effective_user_access(user_id)
    if access["is_premium"]:
        return PREMIUM_MAX_SUBSCRIPTIONS_PER_USER
    return MAX_SUBSCRIPTIONS_PER_USER
