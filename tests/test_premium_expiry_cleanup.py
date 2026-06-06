from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_premium_expiry_cleanup_warns_before_deleting(monkeypatch):
    import bot

    sent = AsyncMock(return_value=True)
    marked = []
    cleanup = AsyncMock()
    monkeypatch.setattr(bot, "MAX_SUBSCRIPTIONS_PER_USER", 15)
    monkeypatch.setattr(bot, "PREMIUM_EXPIRY_GRACE_DAYS", 7)
    monkeypatch.setattr(
        bot,
        "get_expired_premium_overlimit_users",
        lambda _now, _limit, _grace: [
            {
                "user_id": 12345,
                "premium_until": 1000,
                "premium_expiry_notified_at": None,
                "subscription_count": 20,
            }
        ],
    )
    monkeypatch.setattr(bot, "send_notification_with_timeout", sent)
    monkeypatch.setattr(bot, "mark_premium_expiry_notified", lambda user_id, ts: marked.append((user_id, ts)))
    monkeypatch.setattr(bot, "cleanup_user_overlimit_subscriptions", cleanup)

    result = await bot.enforce_premium_expiry_limits(now_ts=1100)

    assert result == {"checked": 1, "warned": 1, "cleaned": 0, "deleted": 0, "failed": 0}
    sent.assert_awaited_once()
    assert marked == [(12345, 1100)]
    cleanup.assert_not_called()


@pytest.mark.asyncio
async def test_premium_expiry_cleanup_deletes_after_grace_period(monkeypatch):
    import bot

    sent = AsyncMock(return_value=True)
    monkeypatch.setattr(bot, "MAX_SUBSCRIPTIONS_PER_USER", 15)
    monkeypatch.setattr(bot, "PREMIUM_EXPIRY_GRACE_DAYS", 7)
    monkeypatch.setattr(
        bot,
        "get_expired_premium_overlimit_users",
        lambda _now, _limit, _grace: [
            {
                "user_id": 12345,
                "premium_until": 1000,
                "premium_expiry_notified_at": 1100,
                "subscription_count": 20,
            }
        ],
    )
    monkeypatch.setattr(bot, "send_notification_with_timeout", sent)
    monkeypatch.setattr(bot, "mark_premium_expiry_notified", lambda *_args: None)
    monkeypatch.setattr(
        bot,
        "cleanup_user_overlimit_subscriptions",
        lambda _user_id, _limit, ts: {
            "kept": [{"id": index} for index in range(15)],
            "deleted": [
                {
                    "id": 99,
                    "product_title": "Deleted <Product>",
                    "url": "https://www.trendyol.com/deleted/product-p-99",
                }
            ],
            "deleted_history": 3,
        },
    )

    result = await bot.enforce_premium_expiry_limits(now_ts=1100 + 7 * 86400)

    assert result == {"checked": 1, "warned": 0, "cleaned": 1, "deleted": 1, "failed": 0}
    sent.assert_awaited_once()
    assert "Deleted &lt;Product&gt;" in sent.await_args.args[1]
