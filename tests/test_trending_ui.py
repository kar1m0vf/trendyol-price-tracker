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


def test_format_trending_items_preserves_detected_currency():
    from bot import format_trending_items
    from scraper import _parse_price_candidate

    price = _parse_price_candidate("163,97 ₼")
    text = format_trending_items(12345, [("Phone", price, "https://trendyol.com/phone-p-1")])

    assert "163.97 ₼" in text
    assert "163.97 TL" not in text


def test_format_trending_items_removes_quick_view_label():
    from bot import format_trending_items, trending_results_kb

    items = [
        ("Hızlı Bakış Samsung Galaxy S25 Ultra", 45000.0, "https://trendyol.com/phone-p-1"),
    ]

    text = format_trending_items(12345, items)
    keyboard = trending_results_kb(12345, items)

    assert "Hızlı" not in text
    assert "bakış" not in text.lower()
    assert "Samsung Galaxy S25 Ultra" in text
    assert "Hızlı" not in keyboard.inline_keyboard[0][0].text


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


@pytest.mark.asyncio
async def test_trending_callback_repeat_uses_cached_result_without_rate_error():
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
    fetch_trends = AsyncMock(return_value=items)

    with patch("scraper.get_trending_all_top3_async", new=fetch_trends):
        await handler.handle_main_callback(cq)
        cq.message.edit_text.reset_mock()
        await handler.handle_main_callback(cq)

    assert fetch_trends.await_count == 1
    assert cq.message.edit_text.await_count >= 1
    assert cq.answer.await_args_list[-1].kwargs.get("show_alert") is not True
    _args, kwargs = cq.message.edit_text.await_args
    assert kwargs["parse_mode"] == "HTML"
    assert kwargs["reply_markup"].inline_keyboard[0][0].url == "https://trendyol.com/phone-p-1"


@pytest.mark.asyncio
async def test_trending_handler_consumes_search_state():
    from handlers.trending_handler import TrendingHandler
    from services.trending_service import TREND_SEARCH_AWAIT

    msg = MagicMock()
    msg.text = "phone"
    msg.from_user.id = 12345
    msg.from_user.username = "user"
    msg.from_user.first_name = "User"
    msg.answer = AsyncMock()

    status_message = MagicMock()
    status_message.edit_text = AsyncMock()

    handler = TrendingHandler()
    handler.send_status_message = AsyncMock(return_value=status_message)

    items = [("Phone", 45000.0, "https://trendyol.com/phone-p-1")]
    TREND_SEARCH_AWAIT.add(12345)
    with patch("handlers.trending_handler.get_trending_by_search_top3_async", new=AsyncMock(return_value=items)):
        await handler.handle_trending_search_text(msg)

    assert 12345 not in TREND_SEARCH_AWAIT
    status_message.edit_text.assert_awaited_once()
    _args, kwargs = status_message.edit_text.await_args
    assert kwargs["parse_mode"] == "HTML"
    assert kwargs["reply_markup"].inline_keyboard[0][0].url == "https://trendyol.com/phone-p-1"


@pytest.mark.asyncio
async def test_trending_button_filter_ignores_trendyol_product_links():
    from handlers.trending_handler import TrendingHandler

    msg = MagicMock()
    msg.text = "https://www.trendyol.com/jeven-brus/kiss-me-erkek-parfum-edp-50-ml-p-841178228?boutiqueId=61"
    msg.from_user.id = 12345

    handler = TrendingHandler()

    assert await handler._is_trending_button(msg) is False


@pytest.mark.asyncio
async def test_trending_search_state_ignores_product_links():
    from handlers.trending_handler import TrendingHandler
    from services.trending_service import TREND_SEARCH_AWAIT

    msg = MagicMock()
    msg.text = "https://www.trendyol.com/jeven-brus/kiss-me-erkek-parfum-edp-50-ml-p-841178228?boutiqueId=61"
    msg.from_user.id = 12345

    handler = TrendingHandler()
    TREND_SEARCH_AWAIT.add(12345)
    try:
        assert await handler._is_trending_search_text(msg) is False
    finally:
        TREND_SEARCH_AWAIT.discard(12345)


@pytest.mark.asyncio
async def test_trending_search_repeat_uses_cached_result_without_fetching_again():
    from handlers.trending_handler import TrendingHandler
    from services.trending_service import TREND_SEARCH_AWAIT

    msg = MagicMock()
    msg.text = "phone"
    msg.from_user.id = 12345
    msg.from_user.username = "user"
    msg.from_user.first_name = "User"
    msg.answer = AsyncMock()

    status_message = MagicMock()
    status_message.edit_text = AsyncMock()

    handler = TrendingHandler()
    handler.send_status_message = AsyncMock(return_value=status_message)

    items = [("Phone", 45000.0, "https://trendyol.com/phone-p-1")]
    fetch_trends = AsyncMock(return_value=items)

    with patch("handlers.trending_handler.get_trending_by_search_top3_async", new=fetch_trends):
        TREND_SEARCH_AWAIT.add(12345)
        await handler.handle_trending_search_text(msg)

        TREND_SEARCH_AWAIT.add(12345)
        msg.answer.reset_mock()
        await handler.handle_trending_search_text(msg)

    assert fetch_trends.await_count == 1
    assert 12345 not in TREND_SEARCH_AWAIT
    msg.answer.assert_awaited_once()
    _args, kwargs = msg.answer.await_args
    assert kwargs["parse_mode"] == "HTML"
    assert kwargs["reply_markup"].inline_keyboard[0][0].url == "https://trendyol.com/phone-p-1"
