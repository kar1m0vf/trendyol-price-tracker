from unittest.mock import AsyncMock

import pytest

import bot
from models.product import ProductSnapshot
from services.product_fetch_service import ProductFetchService


@pytest.mark.asyncio
async def test_scheduler_reuses_one_fetch_for_identical_product_urls(monkeypatch):
    url = "https://www.trendyol.com/brand/shared-product-p-1"
    subscriptions = [
        (1, 101, url, "discount", None, None, None, None, None, None, 60, None, None),
        (2, 202, url, "discount", None, None, None, None, None, None, 60, None, None),
    ]
    fetch_calls = 0

    async def fetch(fetch_url):
        nonlocal fetch_calls
        fetch_calls += 1
        await __import__("asyncio").sleep(0.01)
        return ProductSnapshot(
            url=fetch_url,
            price=1000.0,
            title="Shared product",
        )

    service = ProductFetchService(fetch, ttl_seconds=300)
    monkeypatch.setattr(bot, "product_fetch_service", service)
    monkeypatch.setattr(bot, "get_subscriptions_count", lambda: len(subscriptions))
    monkeypatch.setattr(bot, "iter_all_subscriptions", lambda batch_size=1000: iter(subscriptions))
    monkeypatch.setattr(bot, "get_user_settings", lambda _user_id: ("en", 0, 0))
    monkeypatch.setattr(bot, "clear_subscription_check_failure", lambda _sub_id: None)
    monkeypatch.setattr(bot, "record_subscription_check_failure", lambda *_args: None)
    monkeypatch.setattr(bot, "update_last_price", lambda *_args: None)
    monkeypatch.setattr(bot, "add_price_point", lambda *_args, **_kwargs: 1)
    monkeypatch.setattr(bot, "send_grouped_notifications", AsyncMock())
    monkeypatch.setattr(bot, "action_event", lambda *_args, **_kwargs: None)

    first_result = await bot._check_all_impl(trigger="test")

    assert fetch_calls == 1
    assert first_result["processed"] == 2
    assert first_result["external_fetches"] == 1
    assert first_result["coalesced_fetches"] == 1

    second_result = await bot._check_all_impl(trigger="test")

    assert fetch_calls == 1
    assert second_result["external_fetches"] == 0
    assert second_result["cache_hits"] == 2
