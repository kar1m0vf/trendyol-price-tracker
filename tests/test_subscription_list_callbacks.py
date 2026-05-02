from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from handlers import callback_handler as callback_module
from handlers import CallbackHandler


@pytest.mark.asyncio
async def test_edit_subscription_callback_edits_list_message(monkeypatch):
    handler = CallbackHandler()
    handler._bot = SimpleNamespace(send_message=AsyncMock())

    sub = (
        42,
        12345,
        "https://www.trendyol.com/test/product-p-42",
        "discount",
        199.0,
        "Test product",
        None,
        None,
        None,
        None,
        60,
        None,
        None,
    )
    monkeypatch.setattr(callback_module, "get_subscription", lambda sub_id: sub)

    cq = MagicMock()
    cq.data = "edit_sub:42"
    cq.from_user.id = 12345
    cq.answer = AsyncMock()
    cq.message.edit_text = AsyncMock()

    with patch("bot.format_subscription_card", return_value="CARD"):
        await handler.handle_main_callback(cq)

    cq.answer.assert_awaited()
    cq.message.edit_text.assert_awaited_once()
    handler._bot.send_message.assert_not_awaited()
    assert "CARD" in cq.message.edit_text.await_args.args[0]


@pytest.mark.asyncio
async def test_subscriptions_back_callback_restores_overview(monkeypatch):
    handler = CallbackHandler()

    sub = (
        42,
        12345,
        "https://www.trendyol.com/test/product-p-42",
        "discount",
        199.0,
        "Test product",
        None,
        None,
        None,
        None,
        60,
        None,
        None,
    )
    monkeypatch.setattr(callback_module, "get_user_subscriptions", lambda user_id: [sub])

    cq = MagicMock()
    cq.data = "subs:list"
    cq.from_user.id = 12345
    cq.answer = AsyncMock()
    cq.message.edit_text = AsyncMock()

    with patch("bot.build_subscriptions_overview", return_value=("LIST", None)):
        await handler.handle_main_callback(cq)

    cq.answer.assert_awaited_once()
    cq.message.edit_text.assert_awaited_once()
    assert cq.message.edit_text.await_args.args[0] == "LIST"
