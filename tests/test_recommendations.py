from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import bot
import database


@pytest.fixture()
def temp_database(tmp_path, monkeypatch):
    db_file = tmp_path / "recommendations.db"
    monkeypatch.setattr(database, "DB", str(db_file))
    database.init_db(run_maintenance=False)
    yield db_file
    database.close_all_connections()


def test_preferences_analysis_uses_user_subscriptions(temp_database):
    user_id = 12345
    database.add_subscription(
        user_id,
        "https://www.trendyol.com/apple/iphone-16-pro-p-1",
        product_title="Apple iPhone 16 Pro telefon",
    )

    preferences = bot.analyze_user_preferences(user_id)

    assert preferences["has_subscriptions"] is True
    assert preferences["total_subscriptions"] == 1
    assert preferences["categories"][0][0] == "smartphones"
    assert preferences["brands"][0][0] == "apple"


def test_get_available_products_has_no_built_in_fallback(monkeypatch):
    monkeypatch.setattr(database, "get_recommended_products", lambda: [])

    assert bot.get_available_products() == []


@pytest.mark.asyncio
async def test_recommendations_rank_real_catalog_and_localize_reasons(monkeypatch):
    monkeypatch.setattr(
        bot,
        "analyze_user_preferences",
        lambda _user_id: {
            "has_subscriptions": True,
            "categories": [("smartphones", 1)],
            "brands": [("apple", 1)],
        },
    )

    def fake_t(_user_id, key, **kwargs):
        if kwargs:
            return f"{key}:{kwargs['brand']}"
        return key

    monkeypatch.setattr(bot, "t", fake_t)
    products = [
        {
            "title": "Nike shoes",
            "url": "https://www.trendyol.com/nike/shoes-p-2",
            "price": "1000 TL",
            "category": "shoes",
            "brand": "nike",
            "priority": 10,
        },
        {
            "title": "Apple phone",
            "url": "https://www.trendyol.com/apple/phone-p-1",
            "price": "",
            "category": "smartphones",
            "brand": "Apple",
            "priority": 1,
        },
        {
            "title": "External placeholder",
            "url": "https://example.com/not-trendyol",
            "price": "1 TL",
            "category": "smartphones",
            "brand": "apple",
            "priority": 100,
        },
    ]

    recommendations = await bot.generate_recommendations(
        12345,
        limit=5,
        available_products=products,
    )

    assert [item["title"] for item in recommendations] == ["Apple phone", "Nike shoes"]
    assert recommendations[0]["price"] == "recommend_price_unknown"
    assert recommendations[0]["reason"] == "recommend_reason_brand:Apple"
    assert recommendations[1]["reason"] == "recommend_reason_fashion"


@pytest.mark.asyncio
async def test_recommendations_return_empty_without_subscriptions_or_catalog(monkeypatch):
    monkeypatch.setattr(
        bot,
        "analyze_user_preferences",
        lambda _user_id: {"has_subscriptions": False, "categories": [], "brands": []},
    )
    assert await bot.generate_recommendations(12345, available_products=[]) == []

    monkeypatch.setattr(
        bot,
        "analyze_user_preferences",
        lambda _user_id: {"has_subscriptions": True, "categories": [], "brands": []},
    )
    assert await bot.generate_recommendations(12345, available_products=[]) == []
    assert await bot.generate_recommendations(
        12345,
        limit=0,
        available_products=[{"title": "Unused"}],
    ) == []


@pytest.mark.asyncio
async def test_recommend_command_reports_empty_catalog(monkeypatch):
    message = SimpleNamespace(from_user=SimpleNamespace(id=12345), answer=AsyncMock())
    replace_status = AsyncMock()
    generate = AsyncMock()

    monkeypatch.setattr(bot, "add_user_if_not_exists", lambda _user_id: None)
    monkeypatch.setattr(bot, "check_heavy_command_rate_limit", lambda *_args: 0)
    monkeypatch.setattr(bot, "_send_progress_message", AsyncMock(return_value=object()))
    monkeypatch.setattr(bot, "_replace_progress_message", replace_status)
    monkeypatch.setattr(bot, "get_user_language", lambda _user_id: "en")
    monkeypatch.setattr(bot, "get_bot_text", lambda *_args: None)
    monkeypatch.setattr(bot, "get_available_products", lambda: [])
    monkeypatch.setattr(bot, "generate_recommendations", generate)
    monkeypatch.setattr(bot, "t", lambda _user_id, key, **_kwargs: key)

    await bot.cmd_recommend(message)

    assert replace_status.await_args.args[1] == "recommend_catalog_empty"
    generate.assert_not_awaited()
