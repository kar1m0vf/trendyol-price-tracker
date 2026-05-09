from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


def _fake_t(_user_id, key):
    return {
        "alerts_header": "Alerts <header>",
        "alerts_current": "Current <alert>",
        "alerts_not_set": "Not <set>",
        "btn_edit": "Edit",
        "btn_view_product": "View",
        "cmd_compare_usage": "Compare",
        "recommend_hint": "Hint <safe>",
        "recommend_loading": "Loading",
        "recommend_title": "Recommendations <title>",
    }.get(key, key)


@pytest.mark.asyncio
async def test_alerts_command_escapes_product_title(monkeypatch):
    import bot

    message = SimpleNamespace(
        from_user=SimpleNamespace(id=123),
        answer=AsyncMock(),
    )
    sub = (
        1,
        123,
        "https://www.trendyol.com/product-p-1",
        "discount",
        100.0,
        "Bad <b>Title</b> & Co",
        None,
        None,
        None,
        None,
        60,
        None,
        None,
        None,
    )

    monkeypatch.setattr(bot, "add_user_if_not_exists", lambda _user_id: None)
    monkeypatch.setattr(bot, "get_user_subscriptions", lambda _user_id: [sub])
    monkeypatch.setattr(bot, "t", _fake_t)

    await bot.cmd_alerts(message)

    sent_text = message.answer.call_args.args[0]
    assert "Bad &lt;b&gt;Title&lt;/b&gt; &amp; Co" in sent_text
    assert "Alerts &lt;header&gt;" in sent_text
    assert "Current &lt;alert&gt;" in sent_text


@pytest.mark.asyncio
async def test_compare_urls_escapes_product_titles(monkeypatch):
    import bot

    message = SimpleNamespace(
        from_user=SimpleNamespace(id=123),
        answer=AsyncMock(),
    )
    replace_status = AsyncMock()

    monkeypatch.setattr(bot, "is_trendyol_product_url", lambda _url: True)
    monkeypatch.setattr(bot, "_send_progress_message", AsyncMock(return_value=object()))
    monkeypatch.setattr(bot, "_replace_progress_message", replace_status)
    monkeypatch.setattr(bot, "t", _fake_t)
    monkeypatch.setattr(
        bot,
        "get_product_info_async",
        AsyncMock(side_effect=[
            (10.0, "First <tag> & value", None),
            (20.0, "Second <b>name</b>", None),
        ]),
    )

    await bot._compare_products_by_urls(message, "https://t1", "https://t2")

    sent_text = replace_status.call_args.args[1]
    assert "First &lt;tag&gt; &amp; value" in sent_text
    assert "Second &lt;b&gt;name&lt;/b&gt;" in sent_text


@pytest.mark.asyncio
async def test_recommend_command_escapes_dynamic_fields(monkeypatch):
    import bot

    message = SimpleNamespace(
        from_user=SimpleNamespace(id=123),
        answer=AsyncMock(),
    )
    replace_status = AsyncMock()

    monkeypatch.setattr(bot, "add_user_if_not_exists", lambda _user_id: None)
    monkeypatch.setattr(bot, "_send_progress_message", AsyncMock(return_value=object()))
    monkeypatch.setattr(bot, "_replace_progress_message", replace_status)
    monkeypatch.setattr(bot, "get_user_language", lambda _user_id: "ru")
    monkeypatch.setattr(bot, "get_bot_text", lambda _key, _lang: None)
    monkeypatch.setattr(bot, "t", _fake_t)
    monkeypatch.setattr(
        bot,
        "generate_recommendations",
        AsyncMock(return_value=[
            {
                "title": "Product <script> & name",
                "price": "100 < 200 TL",
                "reason": "Because A & B",
                "url": "https://example.com/item",
            }
        ]),
    )

    await bot.cmd_recommend(message)

    sent_text = replace_status.call_args.args[1]
    assert "Product &lt;script&gt; &amp; name" in sent_text
    assert "100 &lt; 200 TL" in sent_text
    assert "Because A &amp; B" in sent_text
