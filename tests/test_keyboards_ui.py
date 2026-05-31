import keyboards


def test_main_keyboard_uses_localized_labels_without_extra_prefix(monkeypatch):
    labels = {
        "btn_subscribe": "A_SUB",
        "btn_subs": "A_SUBS",
        "btn_trending": "A_TREND",
        "btn_recommend": "A_RECOMMEND",
        "btn_language": "A_LANG",
        "btn_help": "A_HELP",
    }
    monkeypatch.setattr(
        keyboards,
        "translate_func",
        lambda _uid, key: labels[key],
    )

    kb = keyboards.get_main_kb(user_id=101)
    rows = [[btn.text for btn in row] for row in kb.keyboard]

    assert rows == [
        ["A_SUB", "A_SUBS"],
        ["A_TREND", "A_RECOMMEND"],
        ["A_LANG", "A_HELP"],
    ]


def test_subscription_controls_use_unsubscribe_inline_key_and_callback(monkeypatch):
    labels = {
        "btn_mode_hourly": "MODE_HOURLY",
        "btn_mode_discount": "MODE_DISCOUNT",
        "btn_history": "HISTORY",
        "btn_price_alert": "PRICE_ALERT",
        "btn_refresh_price": "REFRESH",
        "btn_unsubscribe_inline": "UNSUB_INLINE",
        "btn_compare": "COMPARE",
    }
    monkeypatch.setattr(
        keyboards,
        "translate_func",
        lambda _uid, key: labels[key],
    )

    import database

    monkeypatch.setattr(
        database,
        "get_subscription",
        lambda _sub_id: (55, 101, "https://www.trendyol.com/p/1", "hourly"),
    )

    kb = keyboards.subscription_controls_kb_for_user(user_id=101, sub_id=55)

    assert kb.inline_keyboard[0][0].text == "MODE_DISCOUNT"
    assert kb.inline_keyboard[0][1].text == "✅ MODE_HOURLY"
    assert kb.inline_keyboard[1][0].text == "REFRESH"
    assert kb.inline_keyboard[1][0].callback_data == "refresh_price:55"
    assert kb.inline_keyboard[2][1].text == "PRICE_ALERT"
    assert kb.inline_keyboard[2][1].callback_data == "alert_edit:55"
    assert kb.inline_keyboard[3][0].text == "COMPARE"
    assert kb.inline_keyboard[3][0].callback_data == "compare:55"
    assert kb.inline_keyboard[3][1].text == "UNSUB_INLINE"
    assert kb.inline_keyboard[3][1].callback_data == "unsubscribe:55"
