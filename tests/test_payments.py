import pytest
from fastapi.testclient import TestClient

from app.core.security import hash_password
from app.main import app
from app.models import User

client = TestClient(app)


def auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def owner_token(accounts, pending_payment):
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
