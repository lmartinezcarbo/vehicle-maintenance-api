import hashlib
import hmac
import json
import time

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.models import Payment

client = TestClient(app)


def sign(payload: bytes) -> str:
    """Reproduce the Stripe-Signature header Stripe would send."""
    timestamp = int(time.time())
    digest = hmac.new(
        settings.stripe_webhook_secret.encode(),
        f"{timestamp}.".encode() + payload,
        hashlib.sha256,
    ).hexdigest()
    return f"t={timestamp},v1={digest}"


def send(event: dict, *, signature="auto"):
    payload = json.dumps(event, separators=(",", ":")).encode()
    header = sign(payload) if signature == "auto" else signature
    return client.post(
        "/payments/webhook",
        content=payload,
        headers={
            "Content-Type": "application/json",
            "Stripe-Signature": header,
        },
    )


def completed_event(payment: Payment, *, amount_total: int, payment_id=None,
                    payment_status="paid"):
    return {
        "id": f"evt_{payment.id}",
        "object": "event",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": f"cs_{payment.id}",
                "payment_status": payment_status,
                "amount_total": amount_total,
                "currency": payment.currency,
                "payment_intent": f"pi_{payment.id}",
                "metadata": {
                    "payment_id": str(payment.id) if payment_id is None else payment_id,
                    "maintenance_record_id": str(payment.maintenance_record_id),
                },
            }
        },
    }


def reload(db, payment):
    db.expire_all()
    return db.query(Payment).filter(Payment.id == payment.id).one()


def test_valid_signature_marks_payment_as_paid(pending_payment, db):
    cents = int(pending_payment.amount * 100)

    response = send(completed_event(pending_payment, amount_total=cents))

    assert response.status_code == 200

    stored = reload(db, pending_payment)
    assert stored.status == "paid"
    assert stored.paid_at is not None
    assert stored.stripe_payment_intent_id == f"pi_{pending_payment.id}"


def test_duplicate_delivery_does_not_rewrite_paid_at(pending_payment, db):
    cents = int(pending_payment.amount * 100)
    event = completed_event(pending_payment, amount_total=cents)

    assert send(event).status_code == 200
    first_paid_at = reload(db, pending_payment).paid_at
    assert first_paid_at is not None

    assert send(event).status_code == 200
    assert reload(db, pending_payment).paid_at == first_paid_at


def test_modified_payload_with_old_signature_is_rejected(pending_payment, db):
    original = json.dumps(
        completed_event(pending_payment, amount_total=5000), separators=(",", ":")
    ).encode()
    modified = json.dumps(
        completed_event(pending_payment, amount_total=999999), separators=(",", ":")
    ).encode()

    response = client.post(
        "/payments/webhook",
        content=modified,
        headers={"Content-Type": "application/json", "Stripe-Signature": sign(original)},
    )

    assert response.status_code == 400
    assert reload(db, pending_payment).status == "pending"


def test_missing_signature_is_rejected(pending_payment, db):
    payload = json.dumps(
        completed_event(pending_payment, amount_total=5000), separators=(",", ":")
    ).encode()

    response = client.post(
        "/payments/webhook",
        content=payload,
        headers={"Content-Type": "application/json", "Stripe-Signature": ""},
    )

    assert response.status_code == 400
    assert reload(db, pending_payment).status == "pending"


def test_unknown_event_type_is_ignored(pending_payment, db):
    event = {
        "id": "evt_other",
        "object": "event",
        "type": "invoice.paid",
        "data": {"object": {"id": "in_1"}},
    }

    response = send(event)

    assert response.status_code == 200
    assert reload(db, pending_payment).status == "pending"


def test_amount_mismatch_keeps_payment_pending(pending_payment, db):
    # Signed correctly, but Stripe reports one cent: we froze 50.00.
    response = send(completed_event(pending_payment, amount_total=1))

    assert response.status_code == 200
    assert reload(db, pending_payment).status == "pending"


def test_non_numeric_payment_id_is_discarded(pending_payment, db):
    response = send(
        completed_event(pending_payment, amount_total=5000, payment_id="not-a-number")
    )

    assert response.status_code == 200
    assert reload(db, pending_payment).status == "pending"


def test_unknown_payment_id_is_discarded(pending_payment, db):
    response = send(
        completed_event(pending_payment, amount_total=5000, payment_id="99999")
    )

    assert response.status_code == 200
    assert reload(db, pending_payment).status == "pending"


def test_unpaid_completion_is_ignored(pending_payment, db):
    # Asynchronous payment methods can emit "completed" before the money lands.
    response = send(
        completed_event(pending_payment, amount_total=5000, payment_status="unpaid")
    )

    assert response.status_code == 200
    assert reload(db, pending_payment).status == "pending"


def test_expired_session_marks_payment_expired(pending_payment, db):
    event = completed_event(pending_payment, amount_total=5000)
    event["type"] = "checkout.session.expired"
    event["data"]["object"]["payment_status"] = "unpaid"

    response = send(event)

    assert response.status_code == 200
    assert reload(db, pending_payment).status == "expired"


def test_failed_async_payment_marks_payment_failed(pending_payment, db):
    event = completed_event(pending_payment, amount_total=5000)
    event["type"] = "checkout.session.async_payment_failed"

    response = send(event)

    assert response.status_code == 200
    assert reload(db, pending_payment).status == "failed"


def test_polling_endpoint_reflects_what_the_webhook_did(pending_payment, db, accounts):
    """The whole loop: webhook updates the row, GET reports it to the client."""
    token = accounts.login(client, "webhook-owner@example.com")

    cents = int(pending_payment.amount * 100)
    assert send(completed_event(pending_payment, amount_total=cents)).status_code == 200

    response = client.get(
        f"/payments/{pending_payment.id}",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "paid"
    assert data["paid_at"] is not None
