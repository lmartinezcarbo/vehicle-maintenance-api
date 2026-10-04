import pytest
from fastapi.testclient import TestClient

from app.core.security import hash_password
from app.main import app
from app.models import MaintenanceRecord, Payment, User

client = TestClient(app)


class FakeStripeSession:
    def __init__(self, session_id, url):
        self.id = session_id
        self.url = url


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def payments_for(db, maintenance_record_id):
    db.expire_all()
    return (
        db.query(Payment)
        .filter(Payment.maintenance_record_id == maintenance_record_id)
        .count()
    )


@pytest.fixture
def owner_token(accounts, ready_record):
    return accounts.login(client, "webhook-owner@example.com")


@pytest.fixture
def other_token(accounts, pending_payment):
    accounts.register(client, "Other Customer", "other-customer@example.com")
    return accounts.login(client, "other-customer@example.com")


@pytest.fixture
def admin_token(accounts, pending_payment, db):
    db.add(
        User(
            name="Payments Admin",
            email="payments-admin@example.com",
            password_hash=hash_password("password123"),
            role="admin",
            email_verified=True,
        )
    )
    db.commit()

    return accounts.login(client, "payments-admin@example.com")


def test_owner_can_read_their_payment(owner_token, pending_payment):
    response = client.get(
        f"/payments/{pending_payment.id}", headers=auth(owner_token)
    )

    assert response.status_code == 200

    data = response.json()
    assert data["id"] == pending_payment.id
    assert data["maintenance_record_id"] == pending_payment.maintenance_record_id
    assert data["status"] == "pending"
    assert data["amount"] == "50.00"
    assert data["paid_at"] is None
    # The checkout link exists only at creation time.
    assert "checkout_url" not in data


def test_another_customer_cannot_read_the_payment(other_token, pending_payment):
    response = client.get(
        f"/payments/{pending_payment.id}", headers=auth(other_token)
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Not authorized to access this payment"


def test_missing_payment_answers_exactly_like_a_forbidden_one(
    owner_token, pending_payment
):
    response = client.get("/payments/99999", headers=auth(owner_token))

    assert response.status_code == 403
    assert response.json()["detail"] == "Not authorized to access this payment"


def test_request_without_token_is_rejected(pending_payment):
    response = client.get(f"/payments/{pending_payment.id}")

    assert response.status_code == 401


def test_admin_can_read_any_payment(admin_token, pending_payment):
    response = client.get(
        f"/payments/{pending_payment.id}", headers=auth(admin_token)
    )

    assert response.status_code == 200
    assert response.json()["status"] == "pending"


def test_first_checkout_is_created_for_a_ready_record(
    ready_record, owner_token, db, monkeypatch
):
    monkeypatch.setattr(
        "app.routers.payments.create_checkout_session",
        lambda **kwargs: FakeStripeSession(
            f"cs_test_{kwargs['payment_id']}",
            f"https://checkout.stripe.com/c/pay/cs_test_{kwargs['payment_id']}",
        ),
    )

    response = client.post(
        "/payments/",
        json={"maintenance_record_id": ready_record.id},
        headers=auth(owner_token),
    )

    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "pending"
    assert data["amount"] == "50.00"
    assert data["checkout_url"].startswith("https://checkout.stripe.com/")
    assert payments_for(db, ready_record.id) == 1


def test_retry_hands_back_the_open_checkout(
    pending_payment, owner_token, db, monkeypatch
):
    pending_payment.stripe_checkout_session_id = "cs_test_open"
    db.commit()

    monkeypatch.setattr(
        "app.routers.payments.get_checkout_url",
        lambda session_id: f"https://checkout.stripe.com/c/pay/{session_id}",
    )
    monkeypatch.setattr(
        "app.routers.payments.create_checkout_session",
        lambda **kwargs: pytest.fail("a second checkout session was created"),
    )

    response = client.post(
        "/payments/",
        json={"maintenance_record_id": pending_payment.maintenance_record_id},
        headers=auth(owner_token),
    )

    assert response.status_code == 200

    data = response.json()
    assert data["id"] == pending_payment.id
    assert data["checkout_url"] == "https://checkout.stripe.com/c/pay/cs_test_open"
    assert payments_for(db, pending_payment.maintenance_record_id) == 1


def test_a_paid_record_cannot_be_charged_again(pending_payment, owner_token, db):
    pending_payment.status = "paid"
    db.commit()

    response = client.post(
        "/payments/",
        json={"maintenance_record_id": pending_payment.maintenance_record_id},
        headers=auth(owner_token),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Maintenance record has already been paid"
    assert payments_for(db, pending_payment.maintenance_record_id) == 1


def test_record_must_be_ready(ready_record, owner_token, db):
    ready_record.status = "in_progress"
    db.commit()

    response = client.post(
        "/payments/",
        json={"maintenance_record_id": ready_record.id},
        headers=auth(owner_token),
    )

    assert response.status_code == 400


def test_another_customer_cannot_pay_someone_elses_record(
    ready_record, other_token
):
    response = client.post(
        "/payments/",
        json={"maintenance_record_id": ready_record.id},
        headers=auth(other_token),
    )

    assert response.status_code == 403


def test_a_completed_record_cannot_be_paid(ready_record, owner_token, db):
    ready_record.status = "completed"
    db.commit()

    response = client.post(
        "/payments/",
        json={"maintenance_record_id": ready_record.id},
        headers=auth(owner_token),
    )

    assert response.status_code == 400
    assert payments_for(db, ready_record.id) == 0


def test_a_completed_record_cannot_be_deleted(ready_record, owner_token, db):
    ready_record.status = "completed"
    db.commit()

    response = client.delete(
        f"/maintenance-records/{ready_record.id}",
        headers=auth(owner_token),
    )

    assert response.status_code == 400
    assert db.query(MaintenanceRecord).filter(
        MaintenanceRecord.id == ready_record.id
    ).count() == 1


def test_an_expense_cannot_change_a_frozen_price(ready_record, admin_token):
    """The total is frozen at "ready": an expense here would break the
    amount check the webhook runs against what Stripe charged."""
    response = client.post(
        "/expenses/",
        json={
            "vehicle_id": ready_record.vehicle_id,
            "maintenance_record_id": ready_record.id,
            "category": "parts",
            "amount": "10.00",
            "expense_date": "2026-10-04T00:00:00Z",
        },
        headers=auth(admin_token),
    )

    assert response.status_code == 400
    assert "Only records in progress can be modified" in response.text
