from datetime import datetime
import time

import bot


def _sub(
    sub_id: int,
    user_id: int = 12345,
    title: str = "Test product",
    mode: str = "discount",
    last_price: float | None = 100.0,
    notify_interval: int = 60,
    last_notify_time: int | None = None,
):
    return (
        sub_id,
        user_id,
        f"https://www.trendyol.com/test/product-p-{sub_id}",
        mode,
        last_price,
        title,
        None,
        90.0,
        120.0,
        None,
        notify_interval,
        last_notify_time,
        None,
    )


def test_subscription_overview_uses_user_facing_numbers():
    subs = [_sub(120, title="First product"), _sub(121, title="Second product")]

    text, keyboard = bot.build_subscriptions_overview(12345, subs)

    assert "\u2116 1" in text
    assert "\u2116 2" in text
    assert "ID 120" not in text
    assert keyboard.inline_keyboard[0][0].text.startswith("\u2116 1")
    assert keyboard.inline_keyboard[0][0].callback_data == "edit_sub:120"
    assert keyboard.inline_keyboard[1][0].text.startswith("\u2116 2")
    assert keyboard.inline_keyboard[1][0].callback_data == "edit_sub:121"


def test_subscription_card_uses_user_facing_number(monkeypatch):
    sub = _sub(120)
    monkeypatch.setattr(bot, "get_user_subscriptions", lambda user_id: [sub])

    text = bot.format_subscription_card(12345, sub)

    assert "\u2116 1" in text
    assert "ID 120" not in text


def test_subscription_card_uses_scheduler_time_for_due_hourly(monkeypatch):
    now = int(time.time())
    next_check = now + 600
    sub = _sub(120, mode="hourly", last_notify_time=now - 3600)
    monkeypatch.setattr(bot, "get_user_subscriptions", lambda user_id: [sub])
    monkeypatch.setattr(bot, "_get_scheduler_next_check_timestamp", lambda: next_check)
    monkeypatch.setattr(bot, "get_user_settings", lambda user_id: ("ru", 0, 0))

    text = bot.format_subscription_card(12345, sub)

    assert datetime.fromtimestamp(next_check).strftime("%H:%M") in text


def test_subscription_card_waits_for_first_price_before_hourly_notification(monkeypatch):
    sub = _sub(120, mode="hourly", last_price=None)
    monkeypatch.setattr(bot, "get_user_subscriptions", lambda user_id: [sub])

    text = bot.format_subscription_card(12345, sub)

    assert bot.t(12345, "next_notify_after_first_check") in text


def test_resolve_user_subscription_ref_prefers_visible_number(monkeypatch):
    subs = [_sub(120, title="First product"), _sub(121, title="Second product")]
    monkeypatch.setattr(bot, "get_user_subscriptions", lambda user_id: subs)
    monkeypatch.setattr(bot, "get_subscription", lambda sub_id: None)

    sub, public_number = bot.resolve_user_subscription_ref(12345, "1")

    assert sub[0] == 120
    assert public_number == 1


def test_resolve_user_subscription_ref_keeps_owned_db_id_fallback(monkeypatch):
    subs = [_sub(500, title="Other product"), _sub(120, title="Old linked product")]
    monkeypatch.setattr(bot, "get_user_subscriptions", lambda user_id: subs)
    monkeypatch.setattr(bot, "get_subscription", lambda sub_id: subs[1] if sub_id == 120 else None)

    sub, public_number = bot.resolve_user_subscription_ref(12345, "120")

    assert sub[0] == 120
    assert public_number == 2
