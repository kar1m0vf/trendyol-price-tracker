import keyboards
from project_links import GITHUB_REPO_URL


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
        "btn_subscribe": "ADD",
        "btn_request_premium": "REQUEST_PREMIUM",
    }
    monkeypatch.setattr(
        keyboards,
        "translate_func",
        lambda _uid, key: labels[key],
    )

    kb = keyboards.get_premium_inline_kb(user_id=101, is_premium=False)

    assert kb.inline_keyboard[0][0].text == "PRODUCTS"
    assert kb.inline_keyboard[0][0].callback_data == "subs:list"
    assert kb.inline_keyboard[0][1].text == "ADD"
    assert kb.inline_keyboard[0][1].callback_data == "onboarding:add"
    assert kb.inline_keyboard[1][0].text == "REQUEST_PREMIUM"
    assert kb.inline_keyboard[1][0].callback_data == "premium:request"


def test_premium_inline_keyboard_hides_request_for_active_premium(monkeypatch):
    labels = {
        "btn_subs": "PRODUCTS",
        "btn_subscribe": "ADD",
    }
    monkeypatch.setattr(
        keyboards,
        "translate_func",
        lambda _uid, key: labels[key],
    )

    kb = keyboards.get_premium_inline_kb(user_id=101, is_premium=True)

    assert len(kb.inline_keyboard) == 1
    assert [button.callback_data for button in kb.inline_keyboard[0]] == [
        "subs:list",
        "onboarding:add",
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
