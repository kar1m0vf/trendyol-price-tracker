from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from handlers.basic import BasicHandler
from handlers.callback_handler import CallbackHandler
import handlers.callback_handler as callback_module


@pytest.mark.asyncio
async def test_basic_help_default_shows_detailed_help_button():
    handler = BasicHandler()
    translations = {
        "help_text": "HELP_TEXT",
        "btn_detailed_help": "DETAIL_BUTTON",
    }
    handler.t = lambda _uid, key, **_kwargs: translations[key]

    message = SimpleNamespace(
        from_user=SimpleNamespace(id=1001),
        text="/help",
        answer=AsyncMock(),
    )

    await handler.handle_help(message)

    message.answer.assert_awaited_once()
    args, kwargs = message.answer.call_args
    assert args[0] == "HELP_TEXT"
    assert "reply_markup" in kwargs
    kb = kwargs["reply_markup"]
    assert kb.inline_keyboard[0][0].text == "DETAIL_BUTTON"
    assert kb.inline_keyboard[0][0].callback_data == "help:full"


@pytest.mark.asyncio
async def test_basic_help_full_shows_full_text_without_button():
    handler = BasicHandler()
    translations = {"help_full": "HELP_FULL_TEXT"}
    handler.t = lambda _uid, key, **_kwargs: translations[key]

    message = SimpleNamespace(
        from_user=SimpleNamespace(id=1002),
        text="/help full",
        answer=AsyncMock(),
    )

    await handler.handle_help(message)

    message.answer.assert_awaited_once_with("HELP_FULL_TEXT")


@pytest.mark.asyncio
async def test_callback_help_full_branch_edits_message():
    handler = CallbackHandler()
    translations = {
        "help_full": "FULL_HELP_FROM_CALLBACK",
        "error_generic": "ERROR",
    }
    handler.t = lambda _uid, key, **_kwargs: translations[key]
    handler._bot = SimpleNamespace(send_message=AsyncMock())

    cq = SimpleNamespace(
        data="help:full",
        from_user=SimpleNamespace(id=42),
        answer=AsyncMock(),
        message=SimpleNamespace(edit_text=AsyncMock()),
    )

    await handler.handle_main_callback(cq)

    cq.answer.assert_awaited_once()
    cq.message.edit_text.assert_awaited_once_with("FULL_HELP_FROM_CALLBACK")


@pytest.mark.asyncio
async def test_callback_language_change_updates_cache(monkeypatch):
    handler = CallbackHandler()
    translations = {
        "start_text": "START_TEXT",
        "lang_changed": "LANG_CHANGED",
        "error_generic": "ERROR",
    }
    handler.t = lambda _uid, key, **_kwargs: translations[key]
    handler._bot = SimpleNamespace(send_message=AsyncMock())

    set_lang_mock = MagicMock()
    cache_mock = MagicMock()
    monkeypatch.setattr(callback_module, "set_user_language", set_lang_mock)
    monkeypatch.setattr(callback_module, "update_language_cache", cache_mock)

    cq = SimpleNamespace(
        data="lang:tr",
        from_user=SimpleNamespace(id=77),
        answer=AsyncMock(),
        message=SimpleNamespace(edit_text=AsyncMock()),
    )

    await handler.handle_main_callback(cq)

    cq.answer.assert_awaited_once()
    set_lang_mock.assert_called_once_with(77, "tr")
    cache_mock.assert_called_once_with(77, "tr")
    handler._bot.send_message.assert_awaited_once()
    cq.message.edit_text.assert_awaited_once_with("LANG_CHANGED")
