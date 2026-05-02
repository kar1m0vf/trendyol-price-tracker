from unittest.mock import AsyncMock, MagicMock, patch

import pytest


ADMIN_ID = 975282591


def test_get_runtime_bot_uses_running_main_module(monkeypatch):
    import sys

    from handlers import admin_handler

    runtime_bot = object()
    monkeypatch.setattr(sys.modules["__main__"], "bot", runtime_bot, raising=False)

    assert admin_handler._get_runtime_bot() is runtime_bot


def _message(text: str):
    msg = MagicMock()
    msg.from_user.id = ADMIN_ID
    msg.chat.id = ADMIN_ID
    msg.text = text
    msg.answer = AsyncMock()
    msg.edit_text = AsyncMock()
    return msg


@pytest.mark.asyncio
async def test_admin_respond_parses_target_user_and_escapes_html():
    from handlers import admin_handler

    msg = _message("/admin respond 12345 Hello <b>user</b>")
    runtime_bot = MagicMock()
    runtime_bot.send_message = AsyncMock()

    with patch.object(admin_handler, "_get_runtime_bot", return_value=runtime_bot):
        await admin_handler.admin_respond(msg)

    runtime_bot.send_message.assert_awaited_once()
    args, kwargs = runtime_bot.send_message.await_args
    assert args[0] == 12345
    assert "Hello &lt;b&gt;user&lt;/b&gt;" in args[1]
    assert kwargs["parse_mode"] == "HTML"
    assert msg.answer.await_count == 1


@pytest.mark.asyncio
async def test_admin_recommend_add_respects_quoted_arguments():
    from handlers import admin_handler

    msg = _message('/admin recommend add "Big Product Name" "https://example.com/item" "100 TL" phones Brand')

    with patch("database.add_recommended_product", return_value=True) as add_product:
        await admin_handler.cmd_admin(msg)

    add_product.assert_called_once()
    args, _kwargs = add_product.call_args
    assert args[:5] == (
        "Big Product Name",
        "https://example.com/item",
        "100 TL",
        "phones",
        "Brand",
    )
    assert msg.answer.await_count == 1


@pytest.mark.asyncio
async def test_admin_broadcast_requires_confirmation_and_escapes_preview():
    from handlers import admin_handler

    admin_handler._PENDING_BROADCASTS.clear()
    msg = _message("/admin broadcast Hello <b>all</b>")

    with patch.object(admin_handler, "_get_broadcast_recipients", return_value=[1, 2, 3]):
        with patch.object(admin_handler, "_send_admin_broadcast", new_callable=AsyncMock) as send_broadcast:
            await admin_handler.admin_broadcast(msg, "Hello <b>all</b>")

    send_broadcast.assert_not_awaited()
    assert len(admin_handler._PENDING_BROADCASTS) == 1
    preview = msg.answer.await_args.args[0]
    assert "Hello &lt;b&gt;all&lt;/b&gt;" in preview
    markup = msg.answer.await_args.kwargs["reply_markup"]
    callbacks = [button.callback_data for row in markup.inline_keyboard for button in row]
    assert any(callback.startswith("admin_broadcast_confirm:") for callback in callbacks)
    assert any(callback.startswith("admin_broadcast_cancel:") for callback in callbacks)


@pytest.mark.asyncio
async def test_admin_cleanup_requires_confirmation_before_delete():
    from handlers import admin_handler

    admin_handler._PENDING_CLEANUPS.clear()
    msg = _message("/admin cleanup")
    preview = {
        "price_history_cutoff": 100,
        "inactive_user_cutoff": 200,
        "old_price_points": 12,
        "inactive_users": 3,
    }

    with patch.object(admin_handler, "_collect_cleanup_preview", return_value=preview):
        with patch.object(admin_handler, "_execute_cleanup") as execute_cleanup:
            await admin_handler.admin_cleanup(msg)

    execute_cleanup.assert_not_called()
    assert len(admin_handler._PENDING_CLEANUPS) == 1
    text = msg.answer.await_args.args[0]
    assert "12" in text
    assert "3" in text
    markup = msg.answer.await_args.kwargs["reply_markup"]
    callbacks = [button.callback_data for row in markup.inline_keyboard for button in row]
    assert any(callback.startswith("admin_cleanup_confirm:") for callback in callbacks)
    assert any(callback.startswith("admin_cleanup_cancel:") for callback in callbacks)


@pytest.mark.asyncio
async def test_admin_cleanup_confirm_creates_backup_then_deletes():
    from handlers import admin_handler

    admin_handler._PENDING_CLEANUPS.clear()
    msg = _message("/admin cleanup")
    token = admin_handler._store_admin_action(
        admin_handler._PENDING_CLEANUPS,
        ADMIN_ID,
        {
            "price_history_cutoff": 100,
            "inactive_user_cutoff": 200,
            "old_price_points": 12,
            "inactive_users": 3,
        },
    )

    with patch.object(
        admin_handler,
        "_create_database_backup",
        new_callable=AsyncMock,
        return_value={"path": "backups/db_backup_test.db", "size_mb": 1.2, "retained": 7},
    ) as create_backup:
        with patch.object(
            admin_handler,
            "_execute_cleanup",
            return_value={"deleted_price_points": 12, "deleted_users": 3},
        ) as execute_cleanup:
            await admin_handler.admin_cleanup_confirm(msg, ADMIN_ID, token)

    create_backup.assert_awaited_once()
    execute_cleanup.assert_called_once()
    assert token not in admin_handler._PENDING_CLEANUPS


@pytest.mark.asyncio
async def test_admin_users_page_callback_passes_offset():
    from handlers.callback_handler import CallbackHandler

    cq = MagicMock()
    cq.answer = AsyncMock()
    cq.message = MagicMock()
    handler = CallbackHandler()

    with patch("handlers.admin_handler.admin_users_list_interactive", new_callable=AsyncMock) as users_page:
        handled = await handler._handle_admin_callback(cq, "admin_users_page:20", ADMIN_ID)

    assert handled is True
    users_page.assert_awaited_once_with(cq.message, offset=20)


@pytest.mark.asyncio
async def test_admin_main_menu_greets_admin_by_name():
    from handlers import admin_handler

    msg = _message("/admin")
    msg.from_user.username = "karim"
    msg.from_user.first_name = "Karim"
    msg.from_user.last_name = "Admin"

    await admin_handler.admin_main_menu(msg)

    text = msg.answer.await_args.args[0]
    assert "Karim Admin (@karim)" in text
    assert f"<code>{ADMIN_ID}</code>" in text


@pytest.mark.asyncio
async def test_user_report_confirmation_uses_html_parse_mode():
    from handlers import admin_handler

    class FakeCursor:
        def execute(self, *_args, **_kwargs):
            return None

        def fetchall(self):
            return []

        def fetchone(self):
            return None

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def cursor(self):
            return FakeCursor()

    msg = _message("report text")
    msg.from_user.id = 12345
    msg.from_user.username = "user"
    msg.from_user.first_name = "User"
    msg.from_user.last_name = None
    runtime_bot = MagicMock()
    runtime_bot.send_message = AsyncMock()

    with patch("database.get_connection", return_value=FakeConnection()):
        with patch.object(admin_handler, "get_user_subscriptions", return_value=[]):
            with patch.object(admin_handler, "_get_runtime_bot", return_value=runtime_bot):
                await admin_handler.submit_user_report(12345, "Something is wrong", msg)

    runtime_bot.send_message.assert_awaited_once()
    assert runtime_bot.send_message.await_args.kwargs["parse_mode"] == "HTML"
    msg.answer.assert_awaited()
    assert msg.answer.await_args.kwargs["parse_mode"] == "HTML"


@pytest.mark.asyncio
async def test_user_report_failure_does_not_confirm_sent():
    from handlers import admin_handler
    from localization import t

    class FakeCursor:
        def execute(self, *_args, **_kwargs):
            return None

        def fetchall(self):
            return []

        def fetchone(self):
            return None

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def cursor(self):
            return FakeCursor()

    msg = _message("report text")
    msg.from_user.id = 12345
    runtime_bot = MagicMock()
    runtime_bot.send_message = AsyncMock(side_effect=RuntimeError("telegram unavailable"))

    with patch("database.get_connection", return_value=FakeConnection()):
        with patch.object(admin_handler, "get_user_subscriptions", return_value=[]):
            with patch.object(admin_handler, "_get_runtime_bot", return_value=runtime_bot):
                await admin_handler.submit_user_report(12345, "Something is wrong", msg)

    runtime_bot.send_message.assert_awaited_once()
    msg.answer.assert_awaited_once_with(t(12345, "report_delivery_failed"))
