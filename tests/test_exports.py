from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram import types


def _fake_t(_user_id, key):
    return {
        "export_done": "exported {path}",
        "history_export_ready": "history {filename}",
    }.get(key, key)


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
