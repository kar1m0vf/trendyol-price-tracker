from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram import types


def _fake_t(_user_id, key, **kwargs):
    text = {
        "export_done": "exported {path}",
        "history_export_ready": "history {filename}",
        "import_help": "IMPORT",
        "import_instruction": "SEND_FILE",
        "import_result": "import {added}/{duplicates}/{invalid}/{failed}",
    }.get(key, key)
    return text.format(**kwargs) if kwargs else text


@pytest.mark.asyncio
async def test_export_sends_csv_from_memory(monkeypatch):
    import bot

    runtime_bot = SimpleNamespace(send_document=AsyncMock())
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=123),
        text="/export csv",
        answer=AsyncMock(),
    )

    monkeypatch.setattr(bot, "bot", runtime_bot)
    monkeypatch.setattr(bot, "t", _fake_t)
    monkeypatch.setattr(
        bot,
        "export_user_subscriptions",
        lambda _user_id: [
            {
                "id": 1,
                "user_id": 123,
                "url": "https://example.com/item",
                "mode": "discount",
                "last_price": 100,
                "product_title": "Item",
                "product_image": "",
                "min_price": "",
                "max_price": "",
                "notify_percent": "",
                "notify_interval": 60,
                "last_notify_time": "",
                "price_alert": "",
                "tags": "",
            }
        ],
    )

    await bot.cmd_export(message)

    document = runtime_bot.send_document.call_args.args[1]
    assert isinstance(document, types.BufferedInputFile)
    assert document.filename.startswith("subscriptions_123_")
    assert not document.filename.startswith("backups/")
    message.answer.assert_awaited()


@pytest.mark.asyncio
async def test_history_export_sends_json_from_memory(monkeypatch):
    import bot

    runtime_bot = SimpleNamespace(send_document=AsyncMock())
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=123),
        text="/history_export 1 json",
        answer=AsyncMock(),
    )
    sub = (5, 123, "https://example.com/item", "discount", 100.0)

    monkeypatch.setattr(bot, "bot", runtime_bot)
    monkeypatch.setattr(bot, "t", _fake_t)
    monkeypatch.setattr(bot, "resolve_user_subscription_ref", lambda _user_id, _ref: (sub, 1))
    monkeypatch.setattr(bot, "get_price_history", lambda _sub_id, limit=5000: [(1710000000, 100.0)])

    await bot.cmd_history_export(message)

    document = runtime_bot.send_document.call_args.args[1]
    assert isinstance(document, types.BufferedInputFile)
    assert document.filename.startswith("history_5_")
    assert not document.filename.startswith("backups/")
    message.answer.assert_awaited()


def test_parse_import_csv_rows():
    import bot

    payload = (
        "\ufeffurl,mode,last_price,product_title\n"
        "https://www.trendyol.com/brand/fresh-product-p-123,hourly,199.5,Fresh product\n"
    ).encode("utf-8")

    rows = bot._parse_import_rows("subscriptions.csv", payload)

    assert rows == [
        {
            "url": "https://www.trendyol.com/brand/fresh-product-p-123",
            "mode": "hourly",
            "last_price": "199.5",
            "product_title": "Fresh product",
        }
    ]


def test_import_subscription_rows_adds_new_and_skips_duplicates(monkeypatch):
    import bot

    existing = (
        1,
        123,
        "https://www.trendyol.com/brand/existing-product-p-1",
        "discount",
        100.0,
        "Existing",
        None,
        None,
        None,
        None,
        60,
        None,
        None,
        None,
    )
    add_subscription = MagicMock(return_value=77)
    update_last_price = MagicMock()
    save_price_point = MagicMock()
    update_settings = MagicMock()
    set_tags = MagicMock()
    set_active = MagicMock()

    monkeypatch.setattr(bot, "get_user_subscriptions", lambda _user_id: [existing])
    monkeypatch.setattr(bot, "add_subscription", add_subscription)
    monkeypatch.setattr(bot, "update_last_price", update_last_price)
    monkeypatch.setattr(bot, "save_price_point", save_price_point)
    monkeypatch.setattr(bot, "update_subscription_settings", update_settings)
    monkeypatch.setattr(bot, "set_subscription_tags", set_tags)
    monkeypatch.setattr(bot, "set_subscription_active", set_active)

    rows = [
        {
            "url": "https://www.trendyol.com/brand/new-product-p-2?utm=1",
            "mode": "hourly",
            "last_price": "199,5",
            "product_title": "New product",
            "product_image": "https://img.example/product.jpg",
            "min_price": "100",
            "max_price": "300",
            "notify_percent": "10",
            "notify_interval": "30",
            "price_alert": "180",
            "tags": "shoes, sale",
            "is_active": "0",
        },
        {"url": "https://www.trendyol.com/brand/existing-product-p-1"},
        {"url": "https://example.com/not-trendyol"},
    ]

    result = bot._import_subscription_rows(123, rows)

    assert result == {
        "total": 3,
        "added": 1,
        "duplicates": 1,
        "invalid": 1,
        "failed": 0,
    }
    add_subscription.assert_called_once_with(
        123,
        "https://www.trendyol.com/brand/new-product-p-2",
        "hourly",
        min_price=100.0,
        max_price=300.0,
        notify_percent=10.0,
        notify_interval=30,
        product_title="New product",
        product_image="https://img.example/product.jpg",
    )
    update_last_price.assert_called_once_with(77, 199.5)
    save_price_point.assert_called_once_with(77, 199.5)
    update_settings.assert_called_once_with(77, price_alert=180.0)
    set_tags.assert_called_once_with(77, ["shoes", "sale"])
    set_active.assert_called_once_with(77, False)


@pytest.mark.asyncio
async def test_import_command_prompts_for_file(monkeypatch):
    import bot

    bot.import_state.discard(123)
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=123),
        text="/import",
        answer=AsyncMock(),
    )

    monkeypatch.setattr(bot, "add_user_if_not_exists", lambda _user_id: None)
    monkeypatch.setattr(bot, "t", _fake_t)

    await bot.cmd_import(message)

    assert 123 in bot.import_state
    message.answer.assert_awaited_once()
    assert "IMPORT" in message.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_handle_import_document_reports_success(monkeypatch):
    import bot

    message = SimpleNamespace(
        from_user=SimpleNamespace(id=123, username="tester"),
        document=SimpleNamespace(file_name="subscriptions.csv", file_size=120),
        answer=AsyncMock(),
    )
    result = {
        "total": 1,
        "added": 1,
        "duplicates": 0,
        "invalid": 0,
        "failed": 0,
    }

    monkeypatch.setattr(bot, "add_user_if_not_exists", lambda _user_id: None)
    monkeypatch.setattr(bot, "_read_import_document_bytes", AsyncMock(return_value=("subscriptions.csv", b"url\nhttps://www.trendyol.com/brand/product-p-1\n")))
    monkeypatch.setattr(bot, "_parse_import_rows", lambda _filename, _payload: [{"url": "https://www.trendyol.com/brand/product-p-1"}])
    monkeypatch.setattr(bot, "_import_subscription_rows", lambda _user_id, _rows: result)
    monkeypatch.setattr(bot, "t", _fake_t)
    monkeypatch.setattr(bot, "action_event", lambda *args, **kwargs: None)

    await bot._handle_import_document(message)

    message.answer.assert_awaited_once_with("import 1/0/0/0")
