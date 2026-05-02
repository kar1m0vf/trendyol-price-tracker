from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import database


@pytest.fixture()
def temp_db_path(tmp_path, monkeypatch):
    db_file = tmp_path / "test_profile_storage.db"
    monkeypatch.setattr(database, "DB", str(db_file))
    database.close_all_connections()
    database.init_db(run_maintenance=False)
    yield str(db_file)
    database.close_all_connections()


def test_save_user_profile_persists_telegram_fields(temp_db_path):
    user = SimpleNamespace(
        id=12345,
        username="karim",
        first_name="Karim",
        last_name="Test",
        language_code="ru",
        is_premium=True,
    )

    database.save_user_profile(user)
    profile = database.get_user_profile(12345)

    assert profile["user_id"] == 12345
    assert profile["username"] == "karim"
    assert profile["first_name"] == "Karim"
    assert profile["last_name"] == "Test"
    assert profile["telegram_language_code"] == "ru"
    assert profile["is_premium"] == 1
    assert profile["last_seen_at"] is not None


def test_save_user_profile_updates_removed_username(temp_db_path):
    database.save_user_profile(
        SimpleNamespace(id=12345, username="old_name", first_name="Karim", last_name=None)
    )
    database.save_user_profile(
        SimpleNamespace(id=12345, username=None, first_name="Karim", last_name=None)
    )

    profile = database.get_user_profile(12345)

    assert profile["username"] is None
    assert profile["first_name"] == "Karim"


@pytest.mark.asyncio
async def test_middleware_saves_profile_before_handler():
    from middleware import AntiSpamMiddleware

    user = SimpleNamespace(id=12345, username="karim", first_name="Karim")
    event = MagicMock()
    event.from_user = user
    handler = AsyncMock(return_value="ok")
    middleware = AntiSpamMiddleware()

    with patch("database.save_user_profile") as save_user_profile:
        result = await middleware(handler, event, {})

    assert result == "ok"
    save_user_profile.assert_called_once_with(user)
    handler.assert_awaited_once()


@pytest.mark.asyncio
async def test_admin_users_list_shows_saved_username(temp_db_path):
    from handlers.admin_handler import admin_users_list

    database.save_user_profile(
        SimpleNamespace(id=12345, username="karim", first_name="Karim", last_name="Test")
    )
    msg = MagicMock()
    msg.from_user.id = 975282591
    msg.chat.id = 975282591
    msg.answer = AsyncMock()

    await admin_users_list(msg)

    text = msg.answer.await_args.args[0]
    assert "Karim Test (@karim)" in text
    assert "<code>12345</code>" in text


@pytest.mark.asyncio
async def test_admin_users_refresh_handles_not_modified(temp_db_path):
    from handlers.admin_handler import admin_users_list_interactive

    database.save_user_profile(
        SimpleNamespace(id=12345, username="karim", first_name="Karim", last_name="Test")
    )
    msg = MagicMock()
    msg.chat.id = 975282591
    msg.from_user.id = 975282591
    msg.edit_text = AsyncMock(
        side_effect=Exception(
            "Bad Request: message is not modified: specified new message content and reply markup are exactly the same"
        )
    )

    await admin_users_list_interactive(msg)

    assert msg.edit_text.await_count == 1


@pytest.mark.asyncio
async def test_admin_users_refresh_shows_total_and_displayed_count(temp_db_path):
    from handlers.admin_handler import admin_users_list_interactive

    database.save_user_profile(
        SimpleNamespace(id=12345, username="karim", first_name="Karim", last_name="Test")
    )
    database.save_user_profile(
        SimpleNamespace(id=67890, username="second", first_name="Second", last_name=None)
    )
    msg = MagicMock()
    msg.chat.id = 975282591
    msg.from_user.id = 975282591
    msg.edit_text = AsyncMock()

    await admin_users_list_interactive(msg)

    text = msg.edit_text.await_args.args[0]
    assert "Всего в базе:</b> 2" in text
    assert "Страница:</b> 1/1" in text
    assert "Показано:</b> 1-2 из 2" in text


@pytest.mark.asyncio
async def test_admin_users_refresh_paginates_all_users(temp_db_path):
    from handlers.admin_handler import admin_users_list_interactive

    for index in range(12):
        database.save_user_profile(
            SimpleNamespace(
                id=10000 + index,
                username=f"user{index}",
                first_name=f"User{index}",
                last_name=None,
            )
        )

    first_page = MagicMock()
    first_page.chat.id = 975282591
    first_page.from_user.id = 975282591
    first_page.edit_text = AsyncMock()

    await admin_users_list_interactive(first_page, offset=0)

    first_text = first_page.edit_text.await_args.args[0]
    first_markup = first_page.edit_text.await_args.kwargs["reply_markup"]
    first_callbacks = [
        button.callback_data
        for row in first_markup.inline_keyboard
        for button in row
    ]
    assert "Страница:</b> 1/2" in first_text
    assert "Показано:</b> 1-10 из 12" in first_text
    assert "admin_users_page:10" in first_callbacks

    second_page = MagicMock()
    second_page.chat.id = 975282591
    second_page.from_user.id = 975282591
    second_page.edit_text = AsyncMock()

    await admin_users_list_interactive(second_page, offset=10)

    second_text = second_page.edit_text.await_args.args[0]
    second_markup = second_page.edit_text.await_args.kwargs["reply_markup"]
    second_callbacks = [
        button.callback_data
        for row in second_markup.inline_keyboard
        for button in row
    ]
    assert "Страница:</b> 2/2" in second_text
    assert "Показано:</b> 11-12 из 12" in second_text
    assert "admin_users_page:0" in second_callbacks
