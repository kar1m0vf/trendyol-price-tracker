from unittest.mock import AsyncMock, MagicMock, patch

import pytest


ADMIN_ID = 975282591


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
