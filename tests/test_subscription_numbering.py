import bot


def _sub(sub_id: int, user_id: int = 12345, title: str = "Test product"):
    return (
        sub_id,
        user_id,
        f"https://www.trendyol.com/test/product-p-{sub_id}",
        "discount",
        100.0,
        title,
        None,
        90.0,
        120.0,
        None,
        60,
        None,
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
