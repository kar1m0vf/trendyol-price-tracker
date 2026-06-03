import access_control


def test_subscription_limit_uses_free_and_premium_tiers(monkeypatch):
    monkeypatch.setattr(access_control, "ADMIN_IDS", [1])
    monkeypatch.setattr(access_control, "MAX_SUBSCRIPTIONS_PER_USER", 5)
    monkeypatch.setattr(access_control, "PREMIUM_MAX_SUBSCRIPTIONS_PER_USER", 50)

    def fake_access(user_id, *, now=None):
        return {
            "is_premium": user_id == 2,
            "is_expired": False,
            "premium_until": None,
            "effective_tier": "premium" if user_id == 2 else "free",
            "access_tier": "premium" if user_id == 2 else "free",
        }

    monkeypatch.setattr(access_control, "get_effective_user_access", fake_access)

    assert access_control.get_subscription_limit_for_user(1) is None
    assert access_control.get_subscription_limit_for_user(2) == 50
    assert access_control.get_subscription_limit_for_user(3) == 5


def test_expired_premium_is_effectively_free(monkeypatch):
    monkeypatch.setattr(
        access_control,
        "get_user_access",
        lambda _user_id: {"access_tier": "premium", "premium_until": 1000},
    )

    access = access_control.get_effective_user_access(123, now=2000)

    assert access["access_tier"] == "premium"
    assert access["effective_tier"] == "free"
    assert access["is_premium"] is False
    assert access["is_expired"] is True
