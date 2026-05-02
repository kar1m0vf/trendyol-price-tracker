from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def test_format_trending_items_uses_cards_without_raw_urls():
    from bot import format_trending_items

    items = [
        ("<b>Phone</b>", 45000.0, "https://trendyol.com/phone-p-1"),
        ("Unknown price product", None, "https://trendyol.com/unknown-p-2"),
    ]

    text = format_trending_items(12345, items)

    assert "<b>&lt;b&gt;Phone&lt;/b&gt;</b>" in text
    assert "45000 TL" in text
    assert "https://trendyol.com" not in text


def test_trending_results_keyboard_uses_url_buttons():
    from bot import trending_results_kb

    items = [("Phone", 45000.0, "https://trendyol.com/phone-p-1")]

    keyboard = trending_results_kb(12345, items)

    assert keyboard.inline_keyboard[0][0].url == "https://trendyol.com/phone-p-1"
    callback_values = [
        button.callback_data
        for row in keyboard.inline_keyboard
        for button in row
        if getattr(button, "callback_data", None)
    ]
    assert "trend:all" in callback_values
    assert "trend:search" in callback_values
    assert "trend:catmenu" in callback_values


def test_trending_fallback_does_not_return_fake_product_urls():
    from scraper import TRENDING_CACHE, get_trending_all_top3, get_trending_by_category_top3, get_trending_by_search_top3

    TRENDING_CACHE.clear()
    with patch("scraper._fetch_first_working_listing", return_value=[]):
        items = (
            get_trending_all_top3()
            + get_trending_by_category_top3("electronics")
            + get_trending_by_search_top3("custom query")
        )

    assert items
    assert all("/sr?q=" in url for _title, _price, url in items)
    assert not any("-p-123456" in url or "-p-789012" in url for _title, _price, url in items)


@pytest.mark.asyncio
async def test_trending_callback_edits_message_with_result_keyboard():
    from handlers.callback_handler import CallbackHandler

    cq = MagicMock()
    cq.data = "trend:all"
    cq.from_user.id = 12345
    cq.answer = AsyncMock()
    cq.message = MagicMock()
    cq.message.edit_text = AsyncMock()

    handler = CallbackHandler()
    handler._bot = MagicMock()
    items = [("Phone", 45000.0, "https://trendyol.com/phone-p-1")]

    with patch("scraper.get_trending_all_top3_async", new=AsyncMock(return_value=items)):
        await handler.handle_main_callback(cq)

    assert cq.message.edit_text.await_count >= 2
    _args, kwargs = cq.message.edit_text.await_args
    assert kwargs["parse_mode"] == "HTML"
    assert kwargs["reply_markup"].inline_keyboard[0][0].url == "https://trendyol.com/phone-p-1"
