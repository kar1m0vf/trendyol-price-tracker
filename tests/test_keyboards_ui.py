import keyboards
from project_links import GITHUB_REPO_URL, USER_GUIDE_URL


def test_main_keyboard_uses_localized_labels_without_extra_prefix(monkeypatch):
    labels = {
        "btn_subscribe": "A_SUB",
        "btn_subs": "A_SUBS",
        "btn_trending": "A_TREND",
        "btn_recommend": "A_RECOMMEND",
        "btn_language": "A_LANG",
        "btn_help": "A_HELP",
        "btn_premium": "A_PREMIUM",
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
        ["A_PREMIUM"],
    ]


def test_onboarding_inline_keyboard_points_to_first_steps(monkeypatch):
    labels = {
        "btn_subscribe": "ADD",
        "btn_subs": "PRODUCTS",
        "btn_trending": "TRENDS",
        "btn_detailed_help": "HELP",
    }
    monkeypatch.setattr(
        keyboards,
        "translate_func",
        lambda _uid, key: labels[key],
    )

    kb = keyboards.get_onboarding_inline_kb(user_id=101)

    assert kb.inline_keyboard[0][0].text == "ADD"
    assert kb.inline_keyboard[0][0].callback_data == "onboarding:add"
    assert kb.inline_keyboard[0][1].text == "TRENDS"
    assert kb.inline_keyboard[0][1].callback_data == "trend:menu"
    assert kb.inline_keyboard[1][0].text == "PRODUCTS"
    assert kb.inline_keyboard[1][0].callback_data == "subs:list"
    assert kb.inline_keyboard[1][1].text == "HELP"
    assert kb.inline_keyboard[1][1].callback_data == "help:full"


def test_help_inline_keyboard_includes_repository_link(monkeypatch):
    labels = {
        "btn_detailed_help": "HELP",
        "btn_github": "GITHUB",
        "btn_user_guide": "GUIDE",
    }
    monkeypatch.setattr(
        keyboards,
        "translate_func",
        lambda _uid, key: labels[key],
    )

    kb = keyboards.get_help_inline_kb(user_id=101)

    assert kb.inline_keyboard[0][0].text == "HELP"
    assert kb.inline_keyboard[0][0].callback_data == "help:full"
    assert kb.inline_keyboard[1][0].text == "GITHUB"
    assert kb.inline_keyboard[1][0].url == GITHUB_REPO_URL
    assert kb.inline_keyboard[2][0].text == "GUIDE"
    assert kb.inline_keyboard[2][0].url == USER_GUIDE_URL


def test_about_inline_keyboard_points_to_user_actions_and_repository(monkeypatch):
    labels = {
        "btn_subscribe": "ADD",
        "btn_subs": "PRODUCTS",
        "btn_github": "GITHUB",
    }
    monkeypatch.setattr(
        keyboards,
        "translate_func",
        lambda _uid, key: labels[key],
    )

    kb = keyboards.get_about_inline_kb(user_id=101)

    assert kb.inline_keyboard[0][0].text == "ADD"
    assert kb.inline_keyboard[0][0].callback_data == "onboarding:add"
    assert kb.inline_keyboard[0][1].text == "PRODUCTS"
    assert kb.inline_keyboard[0][1].callback_data == "subs:list"
    assert kb.inline_keyboard[1][0].text == "GITHUB"
    assert kb.inline_keyboard[1][0].url == GITHUB_REPO_URL


def test_fallback_inline_keyboard_points_to_recovery_actions(monkeypatch):
    labels = {
        "btn_subscribe": "ADD",
        "btn_subs": "PRODUCTS",
        "btn_detailed_help": "HELP",
    }
    monkeypatch.setattr(
        keyboards,
        "translate_func",
        lambda _uid, key: labels[key],
    )

    kb = keyboards.get_fallback_inline_kb(user_id=101)

    assert kb.inline_keyboard[0][0].text == "ADD"
    assert kb.inline_keyboard[0][0].callback_data == "onboarding:add"
    assert kb.inline_keyboard[0][1].text == "PRODUCTS"
    assert kb.inline_keyboard[0][1].callback_data == "subs:list"
    assert kb.inline_keyboard[1][0].text == "HELP"
    assert kb.inline_keyboard[1][0].callback_data == "help:full"


def test_premium_inline_keyboard_offers_request_for_free_users(monkeypatch):
    labels = {
        "btn_subs": "PRODUCTS",
        "btn_support": "SUPPORT",
        "btn_premium_30": "P30",
        "btn_premium_90": "P90",
        "btn_premium_365": "P365",
        "btn_donate": "DONATE",
        "btn_request_premium": "REQUEST_PREMIUM",
    }
    monkeypatch.setattr(
        keyboards,
        "translate_func",
        lambda _uid, key: labels[key],
    )

    kb = keyboards.get_premium_inline_kb(user_id=101, is_premium=False)

    assert [row[0].text for row in kb.inline_keyboard[:4]] == [
        "P30",
        "P90",
        "P365",
        "DONATE",
    ]
    assert [row[0].callback_data for row in kb.inline_keyboard[:4]] == [
        "premium:plan:30",
        "premium:plan:90",
        "premium:plan:365",
        "premium:donate",
    ]
    assert [button.text for button in kb.inline_keyboard[4]] == ["PRODUCTS", "SUPPORT"]
    assert [button.callback_data for button in kb.inline_keyboard[4]] == [
        "subs:list",
        "premium:support",
    ]
    assert kb.inline_keyboard[5][0].text == "REQUEST_PREMIUM"
    assert kb.inline_keyboard[5][0].callback_data == "premium:request"


def test_premium_inline_keyboard_hides_request_for_active_premium(monkeypatch):
    labels = {
        "btn_subs": "PRODUCTS",
        "btn_support": "SUPPORT",
        "btn_premium_30": "P30",
        "btn_premium_90": "P90",
        "btn_premium_365": "P365",
        "btn_donate": "DONATE",
    }
    monkeypatch.setattr(
        keyboards,
        "translate_func",
        lambda _uid, key: labels[key],
    )

    kb = keyboards.get_premium_inline_kb(user_id=101, is_premium=True)

    callbacks = [
        button.callback_data
        for row in kb.inline_keyboard
        for button in row
    ]
    assert callbacks == [
        "premium:plan:30",
        "premium:plan:90",
        "premium:plan:365",
        "premium:donate",
        "subs:list",
        "premium:support",
    ]


def test_subscription_controls_use_unsubscribe_inline_key_and_callback(monkeypatch):
    labels = {
        "btn_mode_hourly": "MODE_HOURLY",
        "btn_mode_discount": "MODE_DISCOUNT",
        "btn_history": "HISTORY",
        "btn_price_alert": "PRICE_ALERT",
        "btn_refresh_price": "REFRESH",
        "btn_subscription_settings": "SETTINGS",
        "btn_pause_subscription": "PAUSE",
        "btn_resume_subscription": "RESUME",
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
    monkeypatch.setattr(database, "get_subscription_active", lambda _sub_id: True)

    kb = keyboards.subscription_controls_kb_for_user(user_id=101, sub_id=55)

    assert kb.inline_keyboard[0][0].text == "MODE_DISCOUNT"
    assert kb.inline_keyboard[0][1].text == "✅ MODE_HOURLY"
    assert kb.inline_keyboard[1][0].text == "REFRESH"
    assert kb.inline_keyboard[1][0].callback_data == "refresh_price:55"
    assert kb.inline_keyboard[1][1].text == "SETTINGS"
    assert kb.inline_keyboard[1][1].callback_data == "sub_settings:55"
    assert kb.inline_keyboard[2][0].text == "PAUSE"
    assert kb.inline_keyboard[2][0].callback_data == "toggle_active:55"
    assert kb.inline_keyboard[3][1].text == "PRICE_ALERT"
    assert kb.inline_keyboard[3][1].callback_data == "alert_edit:55"
    assert kb.inline_keyboard[4][0].text == "COMPARE"
    assert kb.inline_keyboard[4][0].callback_data == "compare:55"
    assert kb.inline_keyboard[4][1].text == "UNSUB_INLINE"
    assert kb.inline_keyboard[4][1].callback_data == "unsubscribe:55"


def test_product_card_keyboard_prioritizes_user_scenario(monkeypatch):
    labels = {
        "btn_view_product": "OPEN",
        "btn_product_details": "DETAILS",
        "btn_refresh_price": "REFRESH",
        "btn_history": "HISTORY",
        "btn_subscription_settings": "SETTINGS",
        "btn_compare": "COMPARE",
        "btn_unsubscribe_inline": "UNSUBSCRIBE",
        "btn_subs": "MY_PRODUCTS",
        "btn_product_compact": "BACK_TO_CARD",
    }
    monkeypatch.setattr(keyboards, "translate_func", lambda _uid, key: labels[key])

    compact = keyboards.product_card_kb_for_user(
        101,
        55,
        "https://www.trendyol.com/brand/product-p-1",
    )
    callbacks = [
        button.callback_data
        for row in compact.inline_keyboard
        for button in row
        if button.callback_data
    ]

    assert compact.inline_keyboard[0][0].url.startswith("https://www.trendyol.com/")
    assert callbacks == [
        "product_details:55",
        "refresh_price:55",
        "history:55",
        "sub_settings:55",
        "compare:55",
        "unsubscribe:55",
        "subs:list",
    ]
    assert not any(value.startswith(("mode:", "toggle_active:", "nav:home")) for value in callbacks)

    expanded = keyboards.product_card_kb_for_user(
        101,
        55,
        "https://www.trendyol.com/brand/product-p-1",
        expanded=True,
    )
    expanded_callbacks = [
        button.callback_data
        for row in expanded.inline_keyboard
        for button in row
        if button.callback_data
    ]
    assert expanded_callbacks == ["product_compact:55"]
