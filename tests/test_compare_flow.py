from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


def _message(text: str, user_id: int = 12345):
    return SimpleNamespace(
        text=text,
        from_user=SimpleNamespace(id=user_id),
        answer=AsyncMock(),
    )


def _sub(sub_id: int, url: str, title: str = "Product", user_id: int = 12345):
    return (
        sub_id,
        user_id,
        url,
        "discount",
        199.0,
        title,
        None,
        None,
        None,
        None,
        60,
        None,
        None,
    )


@pytest.mark.asyncio
async def test_compare_command_one_url_waits_for_second(monkeypatch):
    import bot

    message = _message("/compare https://www.trendyol.com/brand/product-p-1")
    monkeypatch.setattr(bot, "prepare_compare_url", AsyncMock(return_value="https://www.trendyol.com/brand/product-p-1"))
    monkeypatch.setattr(bot, "t", lambda _uid, key, **_kwargs: key)

    await bot.cmd_compare(message)

    assert bot.compare_state[12345]["first"]["url"] == "https://www.trendyol.com/brand/product-p-1"
    message.answer.assert_awaited_once()
    assert message.answer.await_args.args[0] == "compare_first_added"


@pytest.mark.asyncio
async def test_compare_text_second_url_runs_compare_and_clears_state(monkeypatch):
    import bot

    bot.compare_state[12345] = {
        "first": {"url": "https://www.trendyol.com/brand/first-p-1"},
        "created_at": 1,
    }
    compare = AsyncMock()
    monkeypatch.setattr(bot, "_compare_products_by_urls", compare)

    message = _message("https://www.trendyol.com/brand/second-p-2")

    await bot.cmd_compare_text(message)

    compare.assert_awaited_once_with(
        message,
        "https://www.trendyol.com/brand/first-p-1",
        "https://www.trendyol.com/brand/second-p-2",
        apply_rate_limit=False,
    )
    assert 12345 not in bot.compare_state


def test_compare_text_filter_lets_main_menu_buttons_open(monkeypatch):
    import bot

    bot.compare_state[12345] = {
        "first": {"url": "https://www.trendyol.com/brand/first-p-1"},
        "created_at": 1,
    }
    monkeypatch.setattr(bot, "t", lambda _uid, key, **_kwargs: "MY PRODUCTS" if key == "btn_subs" else key)

    message = _message("MY PRODUCTS")

    assert bot._filter_compare_text(message) is False
    assert 12345 not in bot.compare_state


@pytest.mark.asyncio
async def test_compare_command_two_urls_runs_immediately(monkeypatch):
    import bot

    compare = AsyncMock()
    monkeypatch.setattr(bot, "_compare_products_by_urls", compare)
    message = _message(
        "/compare https://www.trendyol.com/brand/first-p-1 https://www.trendyol.com/brand/second-p-2"
    )

    await bot.cmd_compare(message)

    compare.assert_awaited_once_with(
        message,
        "https://www.trendyol.com/brand/first-p-1",
        "https://www.trendyol.com/brand/second-p-2",
    )
    assert 12345 not in bot.compare_state


@pytest.mark.asyncio
async def test_compare_pick_second_subscription_runs_compare(monkeypatch):
    import bot
    from handlers import callback_handler as callback_module
    from handlers import CallbackHandler

    bot.compare_state[12345] = {
        "first": {"url": "https://www.trendyol.com/brand/first-p-1"},
        "created_at": 1,
    }
    sub = _sub(42, "https://www.trendyol.com/brand/second-p-2", "Second product")
    compare = AsyncMock()
    monkeypatch.setattr(callback_module, "get_subscription", lambda _sub_id: sub)
    monkeypatch.setattr(bot, "_compare_products_by_urls", compare)

    handler = CallbackHandler()
    cq = MagicMock()
    cq.data = "compare_pick:42"
    cq.from_user.id = 12345
    cq.answer = AsyncMock()
    cq.message = MagicMock()
    cq.message.edit_text = AsyncMock()

    await handler.handle_main_callback(cq)

    compare.assert_awaited_once_with(
        12345,
        "https://www.trendyol.com/brand/first-p-1",
        "https://www.trendyol.com/brand/second-p-2",
        apply_rate_limit=False,
        status_message=cq.message,
        fallback_target=12345,
    )
    cq.message.edit_text.assert_awaited()
    assert 12345 not in bot.compare_state


@pytest.mark.asyncio
async def test_compare_subs_excludes_first_subscription(monkeypatch):
    import bot
    from handlers import callback_handler as callback_module
    from handlers import CallbackHandler

    bot.compare_state[12345] = {
        "first": {
            "sub_id": 42,
            "url": "https://www.trendyol.com/brand/current-p-1",
        },
        "created_at": 1,
    }
    subs = [
        _sub(42, "https://www.trendyol.com/brand/current-p-1", "Current product"),
        _sub(43, "https://www.trendyol.com/brand/other-p-2", "Other product"),
    ]
    monkeypatch.setattr(callback_module, "get_user_subscriptions", lambda _user_id: subs)
    monkeypatch.setattr(bot, "t", lambda _uid, key, **_kwargs: key)

    handler = CallbackHandler()
    cq = MagicMock()
    cq.data = "compare_subs"
    cq.from_user.id = 12345
    cq.answer = AsyncMock()
    cq.message = MagicMock()
    cq.message.edit_text = AsyncMock()

    await handler.handle_main_callback(cq)

    reply_markup = cq.message.edit_text.await_args.kwargs["reply_markup"]
    callbacks = [
        button.callback_data
        for row in reply_markup.inline_keyboard
        for button in row
    ]
    assert "compare_pick:42" not in callbacks
    assert "compare_pick:43" in callbacks


@pytest.mark.asyncio
async def test_compare_pick_same_subscription_keeps_state(monkeypatch):
    import bot
    from handlers import callback_handler as callback_module
    from handlers import CallbackHandler

    first_url = "https://www.trendyol.com/brand/current-p-1"
    bot.compare_state[12345] = {
        "first": {"sub_id": 42, "url": first_url},
        "created_at": 1,
    }
    monkeypatch.setattr(
        callback_module,
        "get_subscription",
        lambda _sub_id: _sub(42, first_url, "Current product"),
    )
    compare = AsyncMock()
    monkeypatch.setattr(bot, "_compare_products_by_urls", compare)
    monkeypatch.setattr(bot, "t", lambda _uid, key, **_kwargs: key)

    handler = CallbackHandler()
    cq = MagicMock()
    cq.data = "compare_pick:42"
    cq.from_user.id = 12345
    cq.answer = AsyncMock()
    cq.message = MagicMock()

    await handler.handle_main_callback(cq)

    compare.assert_not_awaited()
    cq.answer.assert_awaited_once()
    assert cq.answer.await_args.kwargs == {"show_alert": True}
    assert 12345 in bot.compare_state
