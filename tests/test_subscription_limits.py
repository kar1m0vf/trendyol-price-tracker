from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from handlers import subscription_handler as subscription_module


def _sub(sub_id: int, user_id: int, url: str):
    return (
        sub_id,
        user_id,
        url,
        "discount",
        None,
        None,
        None,
        None,
        None,
        None,
        60,
        None,
        None,
    )


def test_subscription_limit_helper_respects_admin_bypass(monkeypatch):
    monkeypatch.setattr(subscription_module, "ADMIN_IDS", [1])
    monkeypatch.setattr(subscription_module, "MAX_SUBSCRIPTIONS_PER_USER", 2)

    assert subscription_module.is_subscription_limit_reached(2, 1) is False
    assert subscription_module.is_subscription_limit_reached(2, 2) is True
    assert subscription_module.is_subscription_limit_reached(1, 100) is False


@pytest.mark.asyncio
async def test_handle_url_subscription_blocks_regular_user_at_limit(monkeypatch):
    import bot

    user_id = 12345
    handler = subscription_module.SubscriptionHandler()
    handler.t = lambda _user_id, key, **kwargs: (
        f"limit {kwargs['limit']}" if key == "subscription_limit_reached" else key
    )
    handler.send_status_message = AsyncMock()

    monkeypatch.setattr(subscription_module, "ADMIN_IDS", [])
    monkeypatch.setattr(subscription_module, "MAX_SUBSCRIPTIONS_PER_USER", 2)
    monkeypatch.setattr(subscription_module, "add_user_if_not_exists", MagicMock())
    monkeypatch.setattr(subscription_module, "save_user_profile", MagicMock())
    monkeypatch.setattr(
        subscription_module,
        "get_user_subscriptions",
        lambda _user_id: [
            _sub(1, user_id, "https://www.trendyol.com/old-a/p-1"),
            _sub(2, user_id, "https://www.trendyol.com/old-b/p-2"),
        ],
    )
    add_subscription = MagicMock()
    monkeypatch.setattr(subscription_module, "add_subscription", add_subscription)
    monkeypatch.setattr(subscription_module, "action_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(subscription_module, "actor_label", lambda _user: "user")

    monkeypatch.setattr(bot, "extract_supported_url", lambda text: text.strip())
    monkeypatch.setattr(bot, "normalize_url", lambda url: url.rstrip("/"))
    monkeypatch.setattr(bot, "is_trendyol_product_url", lambda _url: True)
    monkeypatch.setattr(bot, "is_trendyol_short_url", lambda _url: False)

    async def resolve_short_url(url):
        return url

    monkeypatch.setattr(bot, "resolve_short_url", resolve_short_url)

    message = SimpleNamespace(
        text="https://www.trendyol.com/new-product/p-3",
        from_user=SimpleNamespace(id=user_id),
        answer=AsyncMock(),
    )

    await handler.handle_url_subscription(message)

    message.answer.assert_awaited_once_with("limit 2")
    add_subscription.assert_not_called()
    handler.send_status_message.assert_not_awaited()
