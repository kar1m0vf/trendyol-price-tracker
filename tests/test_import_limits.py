from unittest.mock import MagicMock


def _sub(sub_id: int, user_id: int, url: str):
    return (
        sub_id,
        user_id,
        url,
        "discount",
        None,
        None,
        None,
        None,
        None,
        None,
        60,
        None,
        None,
    )


def _row(url: str):
    return {"url": url, "mode": "discount"}


def test_import_subscription_rows_respects_user_limit_and_file_order(monkeypatch):
    import bot

    user_id = 12345
    existing = [
        _sub(index, user_id, f"https://www.trendyol.com/existing/product-{index}-p-{index}")
        for index in range(1, 49)
    ]
    existing.append(_sub(49, user_id, "https://www.trendyol.com/brand/duplicate-p-900"))

    added_urls = []
    add_subscription = MagicMock(side_effect=lambda _user_id, url, *_args, **_kwargs: added_urls.append(url) or len(added_urls))

    monkeypatch.setattr(bot, "get_subscription_limit_for_user", lambda _user_id: 51)
    monkeypatch.setattr(bot, "get_user_subscriptions", lambda _user_id: existing)
    monkeypatch.setattr(bot, "add_subscription", add_subscription)
    monkeypatch.setattr(bot, "update_last_price", MagicMock())
    monkeypatch.setattr(bot, "save_price_point", MagicMock())
    monkeypatch.setattr(bot, "update_subscription_settings", MagicMock())
    monkeypatch.setattr(bot, "set_subscription_tags", MagicMock())
    monkeypatch.setattr(bot, "set_subscription_active", MagicMock())

    rows = [
        _row("https://www.trendyol.com/brand/duplicate-p-900"),
        _row("not a link"),
        _row("https://www.trendyol.com/brand/first-p-901"),
        _row("https://www.trendyol.com/brand/second-p-902"),
        _row("https://www.trendyol.com/brand/third-p-903"),
    ]

    result = bot._import_subscription_rows(user_id, rows)

    assert result == {
        "total": 5,
        "added": 2,
        "duplicates": 1,
        "invalid": 1,
        "limit_skipped": 1,
        "failed": 0,
    }
    assert added_urls == [
        "https://www.trendyol.com/brand/first-p-901",
        "https://www.trendyol.com/brand/second-p-902",
    ]


def test_import_subscription_rows_allows_admin_over_limit(monkeypatch):
    import bot

    user_id = 12345
    existing = [
        _sub(index, user_id, f"https://www.trendyol.com/existing/product-{index}-p-{index}")
        for index in range(1, 52)
    ]
    add_subscription = MagicMock(side_effect=[101, 102])

    monkeypatch.setattr(bot, "get_subscription_limit_for_user", lambda _user_id: None)
    monkeypatch.setattr(bot, "get_user_subscriptions", lambda _user_id: existing)
    monkeypatch.setattr(bot, "add_subscription", add_subscription)
    monkeypatch.setattr(bot, "update_last_price", MagicMock())
    monkeypatch.setattr(bot, "save_price_point", MagicMock())
    monkeypatch.setattr(bot, "update_subscription_settings", MagicMock())
    monkeypatch.setattr(bot, "set_subscription_tags", MagicMock())
    monkeypatch.setattr(bot, "set_subscription_active", MagicMock())

    result = bot._import_subscription_rows(
        user_id,
        [
            _row("https://www.trendyol.com/brand/first-p-901"),
            _row("https://www.trendyol.com/brand/second-p-902"),
        ],
    )

    assert result["added"] == 2
    assert result["limit_skipped"] == 0
    assert add_subscription.call_count == 2
