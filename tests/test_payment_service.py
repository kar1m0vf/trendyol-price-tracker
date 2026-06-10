import pytest

import database
from services import payment_service


@pytest.fixture()
def temp_db_path(tmp_path, monkeypatch):
    db_file = tmp_path / "test_payment_service.db"
    database.close_all_connections()
    monkeypatch.setattr(database, "DB", str(db_file))
    database.init_db(run_maintenance=False)
    yield str(db_file)
    database.close_all_connections()


def test_payment_plans_are_defined_for_premium_and_donation():
    premium_plans = payment_service.list_payment_plans(payment_service.PaymentKind.PREMIUM)

    assert [plan.id for plan in premium_plans] == [
        "premium_30",
        "premium_90",
        "premium_365",
    ]
    assert payment_service.premium_plan_id_for_days(30) == "premium_30"
    assert payment_service.get_payment_plan("donation").kind == payment_service.PaymentKind.DONATION


def test_create_pending_payment_event(temp_db_path):
    event = payment_service.create_pending_payment_event(
        12345,
        "premium_30",
        provider="telegram_stars",
        payload={"callback": "premium:plan:30"},
        ts=1000,
    )

    assert event["user_id"] == 12345
    assert event["plan_id"] == "premium_30"
    assert event["kind"] == "premium"
    assert event["status"] == "pending"
    assert event["provider"] == "telegram_stars"
    assert event["premium_days"] == 30
    assert event["payload"] == {"callback": "premium:plan:30"}


def test_apply_successful_premium_payment_grants_access(temp_db_path):
    user_id = 12345
    event = payment_service.create_pending_payment_event(user_id, "premium_30", ts=1000)

    result = payment_service.apply_successful_payment(
        event["id"],
        provider_payment_id="stars-charge-1",
        payload={"telegram": "successful_payment"},
        ts=2000,
    )

    expected_until = 2000 + 30 * 86400
    assert result.applied is True
    assert result.already_applied is False
    assert result.plan.id == "premium_30"
    assert result.premium_until == expected_until
    assert database.get_user_access(user_id) == {
        "access_tier": "premium",
        "premium_until": expected_until,
    }

    paid_event = database.get_payment_event(event["id"])
    assert paid_event["status"] == "paid"
    assert paid_event["provider_payment_id"] == "stars-charge-1"
    assert paid_event["paid_at"] == 2000
    assert paid_event["applied_at"] == 2000


def test_apply_successful_premium_payment_extends_active_access(temp_db_path):
    user_id = 12345
    database.grant_user_premium(user_id, premium_until=5000)
    event = payment_service.create_pending_payment_event(user_id, "premium_30", ts=1000)

    result = payment_service.apply_successful_payment(event["id"], ts=2000)

    assert result.premium_until == 5000 + 30 * 86400
    assert database.get_user_access(user_id)["premium_until"] == 5000 + 30 * 86400


def test_apply_successful_payment_is_idempotent(temp_db_path):
    user_id = 12345
    event = payment_service.create_pending_payment_event(user_id, "premium_30", ts=1000)

    first = payment_service.apply_successful_payment(event["id"], ts=2000)
    second = payment_service.apply_successful_payment(event["id"], ts=3000)

    assert first.applied is True
    assert second.applied is False
    assert second.already_applied is True
    assert database.get_user_access(user_id)["premium_until"] == first.premium_until


def test_apply_successful_donation_payment_does_not_grant_premium(temp_db_path):
    user_id = 12345
    event = payment_service.create_pending_payment_event(user_id, "donation", ts=1000)

    result = payment_service.apply_successful_payment(event["id"], ts=2000)

    assert result.applied is True
    assert result.plan.kind == payment_service.PaymentKind.DONATION
    assert result.premium_until is None
    assert database.get_user_access(user_id) == {
        "access_tier": "free",
        "premium_until": None,
    }
    assert database.get_payment_event(event["id"])["applied_at"] == 2000
