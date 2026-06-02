from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_runtime_alert_uses_cooldown(monkeypatch):
    import bot

    fake_runtime_bot = SimpleNamespace(send_message=AsyncMock())
    bot.runtime_alert_last_sent.clear()

    monkeypatch.setattr(bot, "ADMIN_RUNTIME_ALERTS", True)
    monkeypatch.setattr(bot, "ADMIN_IDS", [111])
    monkeypatch.setattr(bot, "ADMIN_ALERT_COOLDOWN_MINUTES", 30)
    monkeypatch.setattr(bot, "_get_runtime_bot", lambda: fake_runtime_bot)

    first = await bot.send_admin_runtime_alert("same_error", "Title", "Body")
    second = await bot.send_admin_runtime_alert("same_error", "Title", "Body")

    assert first is True
    assert second is False
    fake_runtime_bot.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_scheduled_check_all_sends_alert_on_failed_result(monkeypatch):
    import bot

    check_all = AsyncMock(
        return_value={
            "status": "failed",
            "trigger": "scheduler",
            "reason": "database unavailable",
            "duration_sec": 2.5,
        }
    )
    send_alert = AsyncMock()

    monkeypatch.setattr(bot, "check_all", check_all)
    monkeypatch.setattr(bot, "send_admin_runtime_alert", send_alert)

    result = await bot.scheduled_check_all()

    assert result["status"] == "failed"
    check_all.assert_awaited_once_with(trigger="scheduler")
    send_alert.assert_awaited_once()
    assert send_alert.await_args.args[0] == "scheduled_check_all_failed"


@pytest.mark.asyncio
async def test_scheduled_check_all_does_not_alert_on_completed_result(monkeypatch):
    import bot

    check_all = AsyncMock(
        return_value={
            "status": "completed",
            "trigger": "scheduler",
            "total": 1,
            "processed": 1,
            "failed": 0,
        }
    )
    send_alert = AsyncMock()

    monkeypatch.setattr(bot, "check_all", check_all)
    monkeypatch.setattr(bot, "send_admin_runtime_alert", send_alert)

    result = await bot.scheduled_check_all()

    assert result["status"] == "completed"
    send_alert.assert_not_awaited()
