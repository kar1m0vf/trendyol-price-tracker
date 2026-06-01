from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
import sys

import pytest

from handlers import callback_handler as callback_module
from handlers import CallbackHandler


def test_base_handler_resolves_runtime_bot_from_main_module(monkeypatch):
    from handlers import base

    runtime_bot = SimpleNamespace(send_message=AsyncMock())
    monkeypatch.setattr(base, "_bot", None)
    monkeypatch.setattr(sys.modules["__main__"], "bot", runtime_bot, raising=False)

    assert base.get_bot() is runtime_bot


def test_alert_edit_state_updates_running_main_module(monkeypatch):
    import bot

    main_state = {}
    bot_state = {}
    monkeypatch.setattr(sys.modules["__main__"], "alert_edit_state", main_state, raising=False)
    monkeypatch.setattr(bot, "alert_edit_state", bot_state, raising=False)

    CallbackHandler._set_alert_edit_state(12345, 42)

    assert main_state[12345] == 42
    assert bot_state[12345] == 42


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
async def test_refresh_price_callback_rejects_foreign_subscription(monkeypatch):
    handler = CallbackHandler()
    foreign_sub = (
        42,
        99999,
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
    fetch = AsyncMock(return_value=(179.0, "Fresh title", None))
    handler.send_status_message = AsyncMock()

    monkeypatch.setattr(callback_module, "get_subscription", lambda sub_id: foreign_sub)
    monkeypatch.setattr(callback_module, "get_product_info_async", fetch)

    cq = MagicMock()
    cq.data = "refresh_price:42"
    cq.from_user.id = 12345
    cq.answer = AsyncMock()
    cq.message = MagicMock()

    await handler.handle_main_callback(cq)

    fetch.assert_not_awaited()
    handler.send_status_message.assert_not_awaited()
    cq.answer.assert_awaited_once_with(handler.t(12345, "error_not_your_sub"), show_alert=True)


@pytest.mark.asyncio
async def test_refresh_price_callback_updates_changed_price(monkeypatch):
    handler = CallbackHandler()
    status_message = MagicMock()
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
    fetch = AsyncMock(return_value=(179.0, "Fresh title", "https://img.example/1.jpg"))
    update_last = MagicMock()
    update_meta = MagicMock()
    save_point = MagicMock(return_value=1)
    clear_failure = MagicMock()

    monkeypatch.setattr(callback_module, "get_subscription", lambda sub_id: sub)
    monkeypatch.setattr(callback_module, "get_product_info_async", fetch)
    monkeypatch.setattr(callback_module, "update_last_price", update_last)
    monkeypatch.setattr(callback_module, "update_subscription_meta", update_meta)
    monkeypatch.setattr(callback_module, "save_price_point", save_point)
    monkeypatch.setattr(callback_module, "clear_subscription_check_failure", clear_failure)
    monkeypatch.setattr(callback_module, "action_event", lambda *args, **kwargs: None)
    handler.send_status_message = AsyncMock(return_value=status_message)
    handler.replace_status_message = AsyncMock(return_value=True)
    handler._subscription_detail_keyboard = MagicMock(return_value=None)

    cq = MagicMock()
    cq.data = "refresh_price:42"
    cq.from_user.id = 12345
    cq.answer = AsyncMock()
    cq.message = MagicMock()

    await handler.handle_main_callback(cq)

    fetch.assert_awaited_once_with("https://www.trendyol.com/test/product-p-42")
    update_meta.assert_called_once_with(42, "Fresh title", "https://img.example/1.jpg")
    save_point.assert_called_once_with(42, 179.0)
    update_last.assert_called_once_with(42, 179.0)
    clear_failure.assert_called_once_with(42)
    handler.replace_status_message.assert_awaited_once()
    result_text = handler.replace_status_message.await_args.args[1]
    assert "Fresh title" in result_text
    assert "199" in result_text
    assert "179" in result_text
    assert handler.replace_status_message.await_args.kwargs["parse_mode"] == "HTML"


@pytest.mark.asyncio
async def test_refresh_price_callback_records_failure_when_price_missing(monkeypatch):
    handler = CallbackHandler()
    status_message = MagicMock()
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
    fetch = AsyncMock(return_value=(None, None, None))
    record_failure = MagicMock()
    update_last = MagicMock()
    save_point = MagicMock()

    monkeypatch.setattr(callback_module, "get_subscription", lambda sub_id: sub)
    monkeypatch.setattr(callback_module, "get_product_info_async", fetch)
    monkeypatch.setattr(callback_module, "record_subscription_check_failure", record_failure)
    monkeypatch.setattr(callback_module, "update_last_price", update_last)
    monkeypatch.setattr(callback_module, "save_price_point", save_point)
    handler.send_status_message = AsyncMock(return_value=status_message)
    handler.replace_status_message = AsyncMock(return_value=True)
    handler._subscription_detail_keyboard = MagicMock(return_value=None)

    cq = MagicMock()
    cq.data = "refresh_price:42"
    cq.from_user.id = 12345
    cq.answer = AsyncMock()
    cq.message = MagicMock()

    await handler.handle_main_callback(cq)

    record_failure.assert_called_once_with(42, "manual_price_not_found")
    update_last.assert_not_called()
    save_point.assert_not_called()
    handler.replace_status_message.assert_awaited_once()
    assert handler.t(12345, "refresh_price_unavailable") in handler.replace_status_message.await_args.args[1]


@pytest.mark.asyncio
async def test_subscription_settings_callback_opens_settings_menu(monkeypatch):
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
        180.0,
    )
    monkeypatch.setattr(callback_module, "get_subscription", lambda sub_id: sub)

    cq = MagicMock()
    cq.data = "sub_settings:42"
    cq.from_user.id = 12345
    cq.answer = AsyncMock()
    cq.message.edit_text = AsyncMock()

    await handler.handle_main_callback(cq)

    cq.answer.assert_awaited_once()
    cq.message.edit_text.assert_awaited_once()
    text = cq.message.edit_text.await_args.args[0]
    keyboard = cq.message.edit_text.await_args.kwargs["reply_markup"]
    callbacks = [button.callback_data for row in keyboard.inline_keyboard for button in row]
    assert "Test product" in text
    assert "settings_mode:42:discount" in callbacks
    assert "settings_interval:42:60" in callbacks
    assert "settings_alert_edit:42" in callbacks
    assert "settings_alert_remove:42" in callbacks
    assert "settings_toggle_active:42" in callbacks
    assert "settings_back:42" in callbacks


@pytest.mark.asyncio
async def test_subscription_settings_interval_updates_subscription(monkeypatch):
    handler = CallbackHandler()
    sub = (
        42,
        12345,
        "https://www.trendyol.com/test/product-p-42",
        "hourly",
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
    update_settings = MagicMock()

    monkeypatch.setattr(callback_module, "get_subscription", lambda sub_id: sub)
    monkeypatch.setattr(callback_module, "update_subscription_settings", update_settings)
    monkeypatch.setattr(callback_module, "action_event", lambda *args, **kwargs: None)

    cq = MagicMock()
    cq.data = "settings_interval:42:30"
    cq.from_user.id = 12345
    cq.answer = AsyncMock()
    cq.message.edit_text = AsyncMock()

    await handler.handle_main_callback(cq)

    update_settings.assert_called_once_with(42, notify_interval=30)
    cq.message.edit_text.assert_awaited_once()
    assert cq.answer.await_args.args[0] == handler.t(12345, "subscription_settings_updated")


@pytest.mark.asyncio
async def test_subscription_settings_alert_remove_updates_menu(monkeypatch):
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
        180.0,
    )
    update_settings = MagicMock()

    monkeypatch.setattr(callback_module, "get_subscription", lambda sub_id: sub)
    monkeypatch.setattr(callback_module, "update_subscription_settings", update_settings)
    monkeypatch.setattr(callback_module, "action_event", lambda *args, **kwargs: None)

    cq = MagicMock()
    cq.data = "settings_alert_remove:42"
    cq.from_user.id = 12345
    cq.answer = AsyncMock()
    cq.message.edit_text = AsyncMock()

    await handler.handle_main_callback(cq)

    update_settings.assert_called_once_with(42, price_alert=None)
    cq.message.edit_text.assert_awaited_once()
    assert cq.answer.await_args.args[0] == handler.t(12345, "alerts_removed_success")


@pytest.mark.asyncio
async def test_subscription_toggle_active_pauses_and_refreshes_detail(monkeypatch):
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
    set_active = MagicMock(return_value=True)

    monkeypatch.setattr(callback_module, "get_subscription", lambda sub_id: sub)
    monkeypatch.setattr(callback_module, "get_subscription_active", lambda sub_id: True)
    monkeypatch.setattr(callback_module, "set_subscription_active", set_active)
    monkeypatch.setattr(callback_module, "action_event", lambda *args, **kwargs: None)

    cq = MagicMock()
    cq.data = "toggle_active:42"
    cq.from_user.id = 12345
    cq.answer = AsyncMock()
    cq.message.edit_text = AsyncMock()

    with patch("bot.format_subscription_card", return_value="CARD"):
        await handler.handle_main_callback(cq)

    set_active.assert_called_once_with(42, False)
    cq.message.edit_text.assert_awaited_once()
    assert cq.answer.await_args.args[0] == handler.t(12345, "subscription_paused")


@pytest.mark.asyncio
async def test_subscription_settings_toggle_active_resumes_and_refreshes_menu(monkeypatch):
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
    active_state = {"value": False}
    set_active = MagicMock(return_value=True)

    def fake_get_active(_sub_id):
        return active_state["value"]

    def fake_set_active(_sub_id, active):
        active_state["value"] = active
        return set_active(_sub_id, active)

    monkeypatch.setattr(callback_module, "get_subscription", lambda sub_id: sub)
    monkeypatch.setattr(callback_module, "get_subscription_active", fake_get_active)
    monkeypatch.setattr(callback_module, "set_subscription_active", fake_set_active)
    monkeypatch.setattr(callback_module, "action_event", lambda *args, **kwargs: None)

    cq = MagicMock()
    cq.data = "settings_toggle_active:42"
    cq.from_user.id = 12345
    cq.answer = AsyncMock()
    cq.message.edit_text = AsyncMock()

    await handler.handle_main_callback(cq)

    set_active.assert_called_once_with(42, True)
    cq.message.edit_text.assert_awaited_once()
    assert cq.answer.await_args.args[0] == handler.t(12345, "subscription_resumed")


@pytest.mark.asyncio
async def test_settings_alert_edit_keeps_code_tag_formatted(monkeypatch):
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
    monkeypatch.setattr(
        callback_module.CallbackHandler,
        "t",
        lambda _self, _user_id, key, **_kwargs: {
            "alerts_edit_title": "EDIT ALERT",
            "current_price": "Current",
            "alerts_current": "Alert",
            "alerts_not_set": "not set",
            "alerts_edit_help": "Send <code>price</code>",
            "btn_back": "Back",
        }.get(key, key),
    )

    cq = MagicMock()
    cq.data = "settings_alert_edit:42"
    cq.from_user.id = 12345
    cq.answer = AsyncMock()
    cq.message = MagicMock()

    await handler.handle_main_callback(cq)

    sent_text = handler._bot.send_message.await_args.args[1]
    assert "<code>price</code>" in sent_text
    assert "&lt;code&gt;" not in sent_text
    assert handler._bot.send_message.await_args.kwargs["parse_mode"] == "HTML"


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
