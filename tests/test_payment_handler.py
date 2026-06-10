from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import database
from handlers import payment_handler as payment_module
from handlers.payment_handler import (
    PaymentHandler,
    build_payment_payload,
    clear_donation_amount_entry,
    is_waiting_for_donation_amount,
    parse_payment_payload,
    start_donation_amount_entry,
)
from services import payment_service


@pytest.fixture()
def temp_db_path(tmp_path, monkeypatch):
    db_file = tmp_path / "test_payment_handler.db"
    database.close_all_connections()
    monkeypatch.setattr(database, "DB", str(db_file))
    database.init_db(run_maintenance=False)
    yield str(db_file)
    database.close_all_connections()


def test_payment_payload_helpers():
    assert build_payment_payload(15) == "payment_event:15"
    assert parse_payment_payload("payment_event:15") == 15
    assert parse_payment_payload("payment_event:0") is None
    assert parse_payment_payload("payment_event:not-number") is None
    assert parse_payment_payload("other:15") is None
    assert parse_payment_payload(None) is None


@pytest.mark.asyncio
async def test_pre_checkout_approves_matching_pending_event(monkeypatch):
    handler = PaymentHandler()
    handler.t = lambda _uid, key, **_kwargs: key
    plan = payment_service.get_payment_plan("premium_30")
    monkeypatch.setattr(
        payment_module.database,
        "get_payment_event",
        lambda _event_id: {
            "id": 10,
            "user_id": 42,
            "status": "pending",
            "plan_id": "premium_30",
        },
    )

    query = SimpleNamespace(
        from_user=SimpleNamespace(id=42),
        invoice_payload="payment_event:10",
        total_amount=plan.amount,
        currency="XTR",
        answer=AsyncMock(),
    )

    await handler.handle_pre_checkout_query(query)

    query.answer.assert_awaited_once_with(ok=True)


@pytest.mark.asyncio
async def test_pre_checkout_rejects_amount_mismatch(monkeypatch):
    handler = PaymentHandler()
    handler.t = lambda _uid, key, **_kwargs: key
    plan = payment_service.get_payment_plan("premium_30")
    monkeypatch.setattr(
        payment_module.database,
        "get_payment_event",
        lambda _event_id: {
            "id": 10,
            "user_id": 42,
            "status": "pending",
            "plan_id": "premium_30",
        },
    )

    query = SimpleNamespace(
        from_user=SimpleNamespace(id=42),
        invoice_payload="payment_event:10",
        total_amount=plan.amount + 1,
        currency="XTR",
        answer=AsyncMock(),
    )

    await handler.handle_pre_checkout_query(query)

    query.answer.assert_awaited_once_with(ok=False, error_message="payment_amount_mismatch")


@pytest.mark.asyncio
async def test_pre_checkout_uses_custom_event_amount(monkeypatch):
    handler = PaymentHandler()
    handler.t = lambda _uid, key, **_kwargs: key
    monkeypatch.setattr(
        payment_module.database,
        "get_payment_event",
        lambda _event_id: {
            "id": 10,
            "user_id": 42,
            "status": "pending",
            "plan_id": "donation",
            "amount": 75,
            "currency": "XTR",
        },
    )

    query = SimpleNamespace(
        from_user=SimpleNamespace(id=42),
        invoice_payload="payment_event:10",
        total_amount=75,
        currency="XTR",
        answer=AsyncMock(),
    )

    await handler.handle_pre_checkout_query(query)

    query.answer.assert_awaited_once_with(ok=True)


@pytest.mark.asyncio
async def test_successful_payment_applies_premium_access(temp_db_path):
    user_id = 12345
    event = payment_service.create_pending_payment_event(user_id, "premium_30", ts=1000)
    handler = PaymentHandler()
    handler.t = lambda _uid, key, **kwargs: f"{key}:{kwargs.get('limit', '')}:{kwargs.get('date', '')}"

    successful_payment = SimpleNamespace(
        invoice_payload=build_payment_payload(event["id"]),
        telegram_payment_charge_id="stars-charge-1",
        provider_payment_charge_id=None,
        currency="XTR",
        total_amount=payment_service.get_payment_plan("premium_30").amount,
    )
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=user_id),
        successful_payment=successful_payment,
        answer=AsyncMock(),
    )

    await handler.handle_successful_payment(message)

    access = database.get_user_access(user_id)
    paid_event = database.get_payment_event(event["id"])
    assert access["access_tier"] == "premium"
    assert access["premium_until"] is not None
    assert paid_event["status"] == "paid"
    assert paid_event["provider_payment_id"] == "stars-charge-1"
    assert paid_event["applied_at"] is not None
    message.answer.assert_awaited_once()
    args, kwargs = message.answer.await_args
    assert args[0].startswith("premium_payment_success_until:")
    assert str(payment_module.PREMIUM_MAX_SUBSCRIPTIONS_PER_USER) in args[0]
    assert kwargs["parse_mode"] == "HTML"


@pytest.mark.asyncio
async def test_custom_donation_amount_text_sends_invoice(temp_db_path):
    user_id = 12345
    handler = PaymentHandler()

    def fake_t(_uid, key, **kwargs):
        values = {
            "btn_donate": "DONATE",
            "payment_invoice_description_donation": "DESC {stars}",
            "donation_custom_amount_invalid": "INVALID {min} {max}",
            "payment_invoice_failed": "FAILED",
        }
        return values[key].format(**kwargs)

    handler.t = fake_t
    start_donation_amount_entry(user_id)
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=user_id),
        text="75",
        answer=AsyncMock(),
        answer_invoice=AsyncMock(),
    )

    await handler.handle_donation_amount_text(message)

    assert is_waiting_for_donation_amount(user_id) is False
    message.answer_invoice.assert_awaited_once()
    invoice_kwargs = message.answer_invoice.await_args.kwargs
    assert invoice_kwargs["title"] == "DONATE"
    assert invoice_kwargs["description"] == "DESC 75"
    assert invoice_kwargs["currency"] == "XTR"
    assert invoice_kwargs["prices"][0].amount == 75

    event = database.get_user_payment_events(user_id, limit=1)[0]
    assert event["plan_id"] == "donation"
    assert event["amount"] == 75
    assert event["payload"]["source"] == "donation_custom_amount_text"

    clear_donation_amount_entry(user_id)
