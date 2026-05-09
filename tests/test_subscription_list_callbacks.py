from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from handlers import callback_handler as callback_module
from handlers import CallbackHandler


def test_base_handler_resolves_runtime_bot_from_main_module(monkeypatch):
    import sys
    from handlers import base

    runtime_bot = SimpleNamespace(send_message=AsyncMock())
    monkeypatch.setattr(base, "_bot", None)
    monkeypatch.setattr(sys.modules["__main__"], "bot", runtime_bot, raising=False)

    assert base.get_bot() is runtime_bot


@pytest.mark.asyncio
async def test_callback_history_plot_uses_bound_event_bot():
    handler = CallbackHandler()
    runtime_bot = SimpleNamespace(send_message=AsyncMock(), send_photo=AsyncMock())
    handler.bind_runtime_bot(runtime_bot)

    with patch("services.notification_service.NotificationService") as service_cls:
        service = MagicMock()
        service.send_history_plot = AsyncMock(return_value=True)
        service_cls.return_value = service

        delivered = await handler._send_history_plot(
            12345,
            "https://www.trendyol.com/test/product-p-42",
            [("2026-05-01", 199.0), ("2026-05-02", 189.0)],
        )

    assert delivered is True
    service_cls.assert_called_once_with(runtime_bot)
    service.send_history_plot.assert_awaited_once()


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


@pytest.mark.asyncio
async def test_history_callback_keeps_visible_error_when_plot_delivery_fails(monkeypatch):
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
    status_message = MagicMock()
    monkeypatch.setattr(callback_module, "get_subscription", lambda sub_id: sub)
    monkeypatch.setattr(callback_module, "get_price_history", lambda sub_id, limit=1000: [(100, 199.0), (200, 189.0)])
    handler.send_status_message = AsyncMock(return_value=status_message)
    handler.replace_status_message = AsyncMock(return_value=True)
    handler.clear_status_message = AsyncMock(return_value=True)
    handler._send_history_plot = AsyncMock(return_value=False)

    cq = MagicMock()
    cq.data = "history:42"
    cq.from_user.id = 12345
    cq.answer = AsyncMock()
    cq.message = MagicMock()

    await handler.handle_main_callback(cq)

    handler._send_history_plot.assert_awaited_once()
    handler.clear_status_message.assert_not_awaited()
    handler.replace_status_message.assert_awaited_once()
    assert handler.replace_status_message.await_args.args[0] is status_message
    assert handler.t(12345, "error_generic") in handler.replace_status_message.await_args.args[1]


@pytest.mark.asyncio
async def test_callback_unexpected_error_sends_durable_message(monkeypatch):
    handler = CallbackHandler()
    monkeypatch.setattr(callback_module, "get_user_subscriptions", lambda user_id: (_ for _ in ()).throw(RuntimeError("db down")))

    cq = MagicMock()
    cq.data = "subs:list"
    cq.from_user.id = 12345
    cq.answer = AsyncMock()
    cq.message = MagicMock()
    cq.message.answer = AsyncMock()

    await handler.handle_main_callback(cq)

    cq.message.answer.assert_awaited_once()
    assert handler.t(12345, "error_generic") in cq.message.answer.await_args.args[0]
