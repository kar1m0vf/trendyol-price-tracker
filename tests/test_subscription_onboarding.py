from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from handlers.subscription_handler import SubscriptionHandler
import handlers.subscription_handler as subscription_module


@pytest.mark.asyncio
async def test_subscribe_button_prompts_for_product_link(monkeypatch):
    handler = SubscriptionHandler()
    handler.t = lambda _uid, key, **_kwargs: {"send_link_prompt": "SEND_PRODUCT_LINK"}[key]

    monkeypatch.setattr(
        subscription_module,
        "LOCALES",
        {"test": {"btn_subscribe": "ADD_PRODUCT"}},
    )
    monkeypatch.setattr(
        subscription_module,
        "get_main_kb",
        lambda user_id: "MAIN_KEYBOARD",
    )

    message = SimpleNamespace(
        from_user=SimpleNamespace(id=1001, username="user", first_name="User"),
        text="ADD_PRODUCT",
        answer=AsyncMock(),
    )

    assert await handler._is_subscribe_button(message) is True

    await handler.handle_subscribe_button(message)

    message.answer.assert_awaited_once_with(
        "SEND_PRODUCT_LINK",
        reply_markup="MAIN_KEYBOARD",
    )


@pytest.mark.asyncio
async def test_subscribe_button_ignores_other_text(monkeypatch):
    handler = SubscriptionHandler()
    monkeypatch.setattr(
        subscription_module,
        "LOCALES",
        {"test": {"btn_subscribe": "ADD_PRODUCT"}},
    )

    message = SimpleNamespace(
        from_user=SimpleNamespace(id=1001),
        text="random text",
    )

    assert await handler._is_subscribe_button(message) is False


@pytest.mark.asyncio
async def test_product_link_filter_accepts_tygl_short_links():
    handler = SubscriptionHandler()
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=1001),
        text="https://TY.GL/abc123",
    )

    assert await handler._is_supported_product_link_text(message) is True


@pytest.mark.asyncio
async def test_product_link_filter_accepts_tygl_inside_text():
    handler = SubscriptionHandler()
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=1001),
        text="please track this ty.gl/abc123",
    )

    assert await handler._is_supported_product_link_text(message) is True
