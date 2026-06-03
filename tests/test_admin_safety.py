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
async def test_admin_broken_subscriptions_lists_failures_and_escapes_html():
    from handlers import admin_handler

    msg = _message("/admin broken")
    broken_rows = [
        {
            "id": 7,
            "user_id": 12345,
            "url": "https://example.com/?q=<bad>",
            "notify_mode": "discount",
            "last_price": 1200,
            "product_title": "Sneaker <script>",
            "product_image": None,
            "check_fail_count": 3,
            "last_check_error": "price_not_found <html>",
            "last_check_error_at": 1000,
            "username": "buyer",
            "first_name": "Test",
            "last_name": None,
        }
    ]

    with patch.object(admin_handler, "get_broken_subscriptions", return_value=broken_rows):
        await admin_handler.admin_broken_subscriptions(msg)

    msg.edit_text.assert_awaited_once()
    text = msg.edit_text.await_args.args[0]
    assert "Sneaker &lt;script&gt;" in text
    assert "price_not_found &lt;html&gt;" in text
    assert "https://example.com/?q=&lt;bad&gt;" in text
    assert "fail: <b>3</b>" in text
    markup = msg.edit_text.await_args.kwargs["reply_markup"]
    callbacks = [button.callback_data for row in markup.inline_keyboard for button in row]
    assert "admin_bad_sub:7" in callbacks
    assert "admin_broken_subs" in callbacks
    assert "admin_main_menu" in callbacks


def _broken_subscription_row(**overrides):
    row = {
        "id": 7,
        "user_id": 12345,
        "url": "https://example.com/product-p-7",
        "notify_mode": "discount",
        "last_price": 1200,
        "product_title": "Sneaker <script>",
        "product_image": None,
        "is_active": 1,
        "check_fail_count": 3,
        "last_check_error": "price_not_found <html>",
        "last_check_error_at": 1000,
        "username": "buyer",
        "first_name": "Test",
        "last_name": None,
    }
    row.update(overrides)
    return row


def _callback(data: str):
    cq = MagicMock()
    cq.from_user.id = ADMIN_ID
    cq.data = data
    cq.answer = AsyncMock()
    cq.message = MagicMock()
    cq.message.edit_text = AsyncMock()
    return cq


@pytest.mark.asyncio
async def test_admin_broken_subscriptions_callback_opens_screen():
    from handlers.callback_handler import CallbackHandler

    cq = MagicMock()
    cq.answer = AsyncMock()
    cq.message = MagicMock()
    handler = CallbackHandler()

    with patch("handlers.admin_handler.admin_broken_subscriptions", new_callable=AsyncMock) as broken_screen:
        handled = await handler._handle_admin_callback(cq, "admin_broken_subs", ADMIN_ID)

    assert handled is True
    broken_screen.assert_awaited_once_with(cq.message)


@pytest.mark.asyncio
async def test_admin_health_callback_runs_health_command():
    from handlers.callback_handler import CallbackHandler

    cq = _callback("admin_health")
    handler = CallbackHandler()
    handler.t = lambda _uid, key, **_kwargs: {"loading": "LOADING"}[key]

    with patch("bot.cmd_health", new_callable=AsyncMock) as health_command:
        handled = await handler._handle_admin_callback(cq, "admin_health", ADMIN_ID)

    assert handled is True
    cq.answer.assert_awaited_once_with("LOADING")
    health_command.assert_awaited_once_with(cq.message)


@pytest.mark.asyncio
async def test_admin_premium_callback_shows_help():
    from handlers.callback_handler import CallbackHandler

    cq = _callback("admin_premium")
    handler = CallbackHandler()

    handled = await handler._handle_admin_callback(cq, "admin_premium", ADMIN_ID)

    assert handled is True
    cq.message.edit_text.assert_awaited_once()
    text = cq.message.edit_text.await_args.args[0]
    assert "Premium access" in text
    assert "/admin premium grant USER_ID" in text


@pytest.mark.asyncio
async def test_admin_user_premium_menu_callback_opens_duration_options():
    from handlers.callback_handler import CallbackHandler

    cq = _callback("admin_user_premium:12345")
    handler = CallbackHandler()

    with patch("handlers.admin_handler.admin_user_premium_menu", new_callable=AsyncMock) as menu:
        handled = await handler._handle_admin_callback(cq, "admin_user_premium:12345", ADMIN_ID)

    assert handled is True
    cq.answer.assert_awaited_once()
    menu.assert_awaited_once_with(cq.message, 12345)


@pytest.mark.asyncio
async def test_admin_user_premium_grant_callback_uses_selected_days():
    from handlers.callback_handler import CallbackHandler

    cq = _callback("admin_user_premium_grant:12345:30")
    handler = CallbackHandler()

    with patch("handlers.admin_handler.admin_user_premium_grant", new_callable=AsyncMock) as grant:
        handled = await handler._handle_admin_callback(cq, cq.data, ADMIN_ID)

    assert handled is True
    cq.answer.assert_awaited_once_with("Premium updated")
    grant.assert_awaited_once_with(cq.message, cq.from_user, 12345, 30)


@pytest.mark.asyncio
async def test_admin_user_premium_forever_callback_uses_no_expiry():
    from handlers.callback_handler import CallbackHandler

    cq = _callback("admin_user_premium_grant:12345:forever")
    handler = CallbackHandler()

    with patch("handlers.admin_handler.admin_user_premium_grant", new_callable=AsyncMock) as grant:
        handled = await handler._handle_admin_callback(cq, cq.data, ADMIN_ID)

    assert handled is True
    grant.assert_awaited_once_with(cq.message, cq.from_user, 12345, None)


@pytest.mark.asyncio
async def test_admin_user_premium_revoke_callback():
    from handlers.callback_handler import CallbackHandler

    cq = _callback("admin_user_premium_revoke:12345")
    handler = CallbackHandler()

    with patch("handlers.admin_handler.admin_user_premium_revoke", new_callable=AsyncMock) as revoke:
        handled = await handler._handle_admin_callback(cq, cq.data, ADMIN_ID)

    assert handled is True
    cq.answer.assert_awaited_once_with("Premium removed")
    revoke.assert_awaited_once_with(cq.message, cq.from_user, 12345)


@pytest.mark.asyncio
async def test_admin_bad_subscription_details_escapes_html_and_shows_actions():
    from handlers import callback_handler
    from handlers.callback_handler import CallbackHandler

    cq = _callback("admin_bad_sub:7")
    handler = CallbackHandler()

    with patch("config.ADMIN_IDS", [ADMIN_ID]):
        with patch.object(callback_handler, "get_subscription_failure_details", return_value=_broken_subscription_row()):
            handled = await handler._handle_admin_callback(cq, cq.data, ADMIN_ID)

    assert handled is True
    cq.message.edit_text.assert_awaited_once()
    text = cq.message.edit_text.await_args.args[0]
    assert "Sneaker &lt;script&gt;" in text
    assert "price_not_found &lt;html&gt;" in text
    markup = cq.message.edit_text.await_args.kwargs["reply_markup"]
    callbacks = [button.callback_data for row in markup.inline_keyboard for button in row]
    assert "admin_bad_recheck:7" in callbacks
    assert "admin_bad_pause:7" in callbacks
    assert "admin_bad_delete:7" in callbacks


@pytest.mark.asyncio
async def test_admin_bad_subscription_pause_sets_inactive():
    from handlers import callback_handler
    from handlers.callback_handler import CallbackHandler

    cq = _callback("admin_bad_pause:7")
    handler = CallbackHandler()

    with patch("config.ADMIN_IDS", [ADMIN_ID]):
        with patch.object(callback_handler, "get_subscription_failure_details", return_value=_broken_subscription_row()):
            with patch.object(callback_handler, "set_subscription_active", return_value=True) as set_active:
                with patch.object(callback_handler, "action_event"):
                    handled = await handler._handle_admin_callback(cq, cq.data, ADMIN_ID)

    assert handled is True
    set_active.assert_called_once_with(7, False)
    cq.message.edit_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_admin_bad_subscription_delete_requires_confirm_then_removes():
    from handlers import callback_handler
    from handlers.callback_handler import CallbackHandler

    handler = CallbackHandler()
    prompt_cq = _callback("admin_bad_delete:7")
    confirm_cq = _callback("admin_bad_delete_confirm:7")

    with patch("config.ADMIN_IDS", [ADMIN_ID]):
        with patch.object(callback_handler, "get_subscription_failure_details", return_value=_broken_subscription_row()):
            handled_prompt = await handler._handle_admin_callback(prompt_cq, prompt_cq.data, ADMIN_ID)
        with patch.object(callback_handler, "remove_subscription", return_value=True) as remove_subscription:
            with patch.object(callback_handler, "action_event"):
                handled_confirm = await handler._handle_admin_callback(confirm_cq, confirm_cq.data, ADMIN_ID)

    assert handled_prompt is True
    prompt_markup = prompt_cq.message.edit_text.await_args.kwargs["reply_markup"]
    prompt_callbacks = [button.callback_data for row in prompt_markup.inline_keyboard for button in row]
    assert "admin_bad_delete_confirm:7" in prompt_callbacks
    assert handled_confirm is True
    remove_subscription.assert_called_once_with(7)
    assert "Sub: <code>7</code>" in confirm_cq.message.edit_text.await_args.args[0]


@pytest.mark.asyncio
async def test_admin_bad_subscription_recheck_success_clears_failure():
    from handlers import callback_handler
    from handlers.callback_handler import CallbackHandler

    cq = _callback("admin_bad_recheck:7")
    handler = CallbackHandler()

    with patch("config.ADMIN_IDS", [ADMIN_ID]):
        with patch.object(callback_handler, "get_subscription_failure_details", return_value=_broken_subscription_row()):
            with patch.object(callback_handler, "get_product_info_async", new_callable=AsyncMock, return_value=(999.0, "Fresh title", None)):
                with patch.object(callback_handler, "update_subscription_meta") as update_meta:
                    with patch.object(callback_handler, "update_last_price") as update_last_price:
                        with patch.object(callback_handler, "add_price_point") as add_price_point:
                            with patch.object(callback_handler, "clear_subscription_check_failure") as clear_failure:
                                with patch.object(callback_handler, "action_event"):
                                    handled = await handler._handle_admin_callback(cq, cq.data, ADMIN_ID)

    assert handled is True
    update_meta.assert_called_once_with(7, "Fresh title", None)
    update_last_price.assert_called_once_with(7, 999.0)
    add_price_point.assert_called_once_with(7, "https://example.com/product-p-7", 999.0, source="admin_recheck")
    clear_failure.assert_called_once_with(7)
    assert "999 TL" in cq.message.edit_text.await_args.args[0]


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
    markup = msg.answer.await_args.kwargs["reply_markup"]
    callbacks = [button.callback_data for row in markup.inline_keyboard for button in row]
    assert "admin_health" in callbacks
    assert "admin_premium" in callbacks


@pytest.mark.asyncio
async def test_admin_user_details_callback_has_premium_button():
    from handlers import admin_handler
    import database

    target_user_id = 12345
    msg = _message("/admin users 12345")

    class FakeCursor:
        def execute(self, *_args, **_kwargs):
            return None

        def fetchall(self):
            return [
                (0, "user_id"),
                (1, "language"),
                (2, "notify_quiet_hours_start"),
                (3, "notify_quiet_hours_end"),
                (4, "created_at"),
                (5, "username"),
                (6, "first_name"),
                (7, "last_name"),
                (8, "telegram_language_code"),
                (9, "is_premium"),
                (10, "last_seen_at"),
            ]

        def fetchone(self):
            return (
                target_user_id,
                "ru",
                23,
                7,
                1000,
                "buyer",
                "Test",
                None,
                "ru",
                0,
                2000,
            )

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def cursor(self):
            return FakeCursor()

    fake_bot = MagicMock()
    fake_bot.get_chat_member = AsyncMock(side_effect=RuntimeError("telegram unavailable"))

    with patch.object(database, "get_connection", return_value=FakeConnection()):
        with patch.object(database, "get_user_subscriptions", return_value=[]):
            with patch.object(admin_handler, "_get_runtime_bot", return_value=fake_bot):
                with patch.object(admin_handler, "_format_bot_access", return_value="free; limit: 50"):
                    await admin_handler.admin_user_details_callback(msg, target_user_id, ADMIN_ID)

    markup = msg.edit_text.await_args.kwargs["reply_markup"]
    callbacks = [button.callback_data for row in markup.inline_keyboard for button in row]
    assert f"admin_user_premium:{target_user_id}" in callbacks


@pytest.mark.asyncio
async def test_admin_premium_grant_with_days(monkeypatch):
    from handlers import admin_handler

    msg = _message("/admin premium grant 12345 30")
    monkeypatch.setattr(admin_handler.time, "time", lambda: 1000)

    with patch.object(admin_handler, "grant_user_premium") as grant:
        with patch.object(admin_handler, "_format_bot_access", return_value="premium до 01.01.2030; лимит: 200 товаров"):
            await admin_handler.cmd_admin(msg)

    grant.assert_called_once_with(12345, premium_until=1000 + 30 * 86400)
    assert "Premium выдан" in msg.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_admin_premium_revoke():
    from handlers import admin_handler

    msg = _message("/admin premium revoke 12345")

    with patch.object(admin_handler, "revoke_user_premium") as revoke:
        with patch.object(admin_handler, "_format_bot_access", return_value="free; лимит: 50 товаров"):
            await admin_handler.cmd_admin(msg)

    revoke.assert_called_once_with(12345)
    assert "Premium снят" in msg.answer.await_args.args[0]


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
