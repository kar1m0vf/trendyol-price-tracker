from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from handlers.basic import BasicHandler
import handlers.basic as basic_module
from handlers.callback_handler import CallbackHandler
import handlers.callback_handler as callback_module


@pytest.mark.asyncio
async def test_basic_help_default_shows_detailed_help_button(monkeypatch):
    handler = BasicHandler()
    translations = {"help_text": "HELP_TEXT"}
    handler.t = lambda _uid, key, **_kwargs: translations[key]
    help_kb = MagicMock(return_value="HELP_KB")
    monkeypatch.setattr(basic_module, "get_help_inline_kb", help_kb)

    message = SimpleNamespace(
        from_user=SimpleNamespace(id=1001),
        text="/help",
        answer=AsyncMock(),
    )

    await handler.handle_help(message)

    message.answer.assert_awaited_once()
    args, kwargs = message.answer.call_args
    assert args[0] == "HELP_TEXT"
    assert kwargs["reply_markup"] == "HELP_KB"
    help_kb.assert_called_once_with(1001)


@pytest.mark.asyncio
async def test_basic_start_new_user_sends_quick_actions(monkeypatch):
    handler = BasicHandler()
    translations = {
        "start_text_named": "Hi, {name}!",
        "start_text": "Hi!",
        "onboarding_quick_actions": "FIRST_STEP",
    }
    handler.t = lambda _uid, key, **_kwargs: translations[key]

    monkeypatch.setattr(basic_module, "get_user_profile", lambda _user_id: None)
    monkeypatch.setattr(basic_module, "add_user_if_not_exists", lambda _user_id: None)
    monkeypatch.setattr(basic_module, "save_user_profile", lambda _user: None)
    monkeypatch.setattr(basic_module, "set_user_language", lambda _user_id, _lang: None)
    monkeypatch.setattr(basic_module, "update_language_cache", lambda _user_id, _lang: None)
    monkeypatch.setattr(basic_module, "get_main_kb", lambda _user_id: "MAIN_KB")
    monkeypatch.setattr(basic_module, "get_onboarding_inline_kb", lambda _user_id: "ONBOARDING_KB")

    message = SimpleNamespace(
        from_user=SimpleNamespace(id=1001, first_name="Karim", username="karim", language_code="en"),
        text="/start",
        answer=AsyncMock(),
    )

    await handler.handle_start(message)

    assert message.answer.await_count == 2
    assert message.answer.await_args_list[0].args[0] == "Hi, Karim!"
    assert message.answer.await_args_list[0].kwargs["reply_markup"] == "MAIN_KB"
    assert message.answer.await_args_list[1].args[0] == "FIRST_STEP"
    assert message.answer.await_args_list[1].kwargs["reply_markup"] == "ONBOARDING_KB"


@pytest.mark.asyncio
async def test_basic_start_existing_user_keeps_language_and_skips_quick_actions(monkeypatch):
    handler = BasicHandler()
    translations = {
        "start_text_named": "Hi, {name}!",
        "start_text": "Hi!",
    }
    handler.t = lambda _uid, key, **_kwargs: translations[key]

    set_language = MagicMock()
    update_cache = MagicMock()
    monkeypatch.setattr(basic_module, "get_user_profile", lambda _user_id: {"language": "ru"})
    monkeypatch.setattr(basic_module, "add_user_if_not_exists", lambda _user_id: None)
    monkeypatch.setattr(basic_module, "save_user_profile", lambda _user: None)
    monkeypatch.setattr(basic_module, "set_user_language", set_language)
    monkeypatch.setattr(basic_module, "update_language_cache", update_cache)
    monkeypatch.setattr(basic_module, "get_main_kb", lambda _user_id: "MAIN_KB")

    message = SimpleNamespace(
        from_user=SimpleNamespace(id=1001, first_name="Karim", username="karim", language_code="en"),
        text="/start",
        answer=AsyncMock(),
    )

    await handler.handle_start(message)

    message.answer.assert_awaited_once()
    set_language.assert_not_called()
    update_cache.assert_called_once_with(1001, "ru")


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


@pytest.mark.parametrize(
    ("method_name", "key", "expected"),
    [
        ("handle_terms", "terms_text", "TERMS_TEXT"),
        ("handle_privacy", "privacy_text", "PRIVACY_TEXT"),
        ("handle_support", "support_text", "SUPPORT_TEXT"),
    ],
)
@pytest.mark.asyncio
async def test_basic_legal_commands_send_html(method_name, key, expected):
    handler = BasicHandler()
    handler.t = lambda _uid, requested_key, **_kwargs: {key: expected}[requested_key]

    message = SimpleNamespace(
        from_user=SimpleNamespace(id=1004),
        text=f"/{method_name.removeprefix('handle_')}",
        answer=AsyncMock(),
    )

    await getattr(handler, method_name)(message)

    message.answer.assert_awaited_once_with(
        expected,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


@pytest.mark.asyncio
async def test_basic_delete_me_requires_confirmation(monkeypatch):
    handler = BasicHandler()
    handler.t = lambda _uid, key, **_kwargs: {"delete_me_confirm_text": "CONFIRM_DELETE"}[key]
    delete_mock = MagicMock()
    monkeypatch.setattr(basic_module, "delete_user_data", delete_mock)

    message = SimpleNamespace(
        from_user=SimpleNamespace(id=1005),
        text="/delete_me",
        answer=AsyncMock(),
    )

    await handler.handle_delete_me(message)

    delete_mock.assert_not_called()
    message.answer.assert_awaited_once_with(
        "CONFIRM_DELETE",
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


@pytest.mark.asyncio
async def test_basic_delete_me_confirm_deletes_data(monkeypatch):
    handler = BasicHandler()
    handler.t = lambda _uid, key, **_kwargs: {
        "delete_me_done": "DONE {subscriptions} {price_history}",
        "error_generic": "ERROR",
    }[key]
    delete_mock = MagicMock(
        return_value={"users": 1, "subscriptions": 2, "price_history": 5}
    )
    clear_cache_mock = MagicMock()
    monkeypatch.setattr(basic_module, "delete_user_data", delete_mock)
    monkeypatch.setattr(basic_module, "clear_language_cache", clear_cache_mock)

    message = SimpleNamespace(
        from_user=SimpleNamespace(id=1006, username="karim", first_name="Karim"),
        text="/delete_me confirm",
        answer=AsyncMock(),
    )

    await handler.handle_delete_me(message)

    delete_mock.assert_called_once_with(1006)
    clear_cache_mock.assert_called_once_with(1006)
    message.answer.assert_awaited_once_with(
        "DONE 2 5",
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


@pytest.mark.asyncio
async def test_basic_fallback_guides_unrecognized_text(monkeypatch):
    handler = BasicHandler()
    handler.t = lambda _uid, key, **_kwargs: {"fallback_text": "SEND_LINK_HINT"}[key]
    fallback_kb = MagicMock(return_value="FALLBACK_KB")
    monkeypatch.setattr(basic_module, "get_fallback_inline_kb", fallback_kb)

    message = SimpleNamespace(
        from_user=SimpleNamespace(id=1003),
        text="hello",
        answer=AsyncMock(),
    )

    await handler.handle_unrecognized_text(message)

    message.answer.assert_awaited_once_with(
        "SEND_LINK_HINT",
        reply_markup="FALLBACK_KB",
    )
    fallback_kb.assert_called_once_with(1003)


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
async def test_callback_onboarding_add_prompts_for_link():
    handler = CallbackHandler()
    translations = {
        "send_link_prompt": "SEND_LINK",
        "error_generic": "ERROR",
    }
    handler.t = lambda _uid, key, **_kwargs: translations[key]

    cq = SimpleNamespace(
        data="onboarding:add",
        from_user=SimpleNamespace(id=42),
        answer=AsyncMock(),
        message=SimpleNamespace(answer=AsyncMock()),
    )

    await handler.handle_main_callback(cq)

    cq.answer.assert_awaited_once()
    cq.message.answer.assert_awaited_once()
    assert cq.message.answer.await_args.args[0] == "SEND_LINK"
    assert "reply_markup" in cq.message.answer.await_args.kwargs


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
