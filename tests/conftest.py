import os
import re
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config
from dotenv import load_dotenv
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import sessionmaker

from app.core.rate_limit import limiter
from app.core.security import hash_password
from app.database import Base, get_db
from app.main import app
from app.models import *

load_dotenv()

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")

test_engine = create_engine(TEST_DATABASE_URL)

# 1. Start from an empty schema on every test run.
with test_engine.begin() as conn:
    conn.exec_driver_sql("DROP SCHEMA public CASCADE")
    conn.exec_driver_sql("CREATE SCHEMA public")

# 2. Rebuild it exactly like production does: with the real migrations.
#    alembic/env.py reads DATABASE_URL, so we point it at the test database
#    while the migrations run.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
alembic_cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
command.upgrade(alembic_cfg, "head")

TestSessionLocal = sessionmaker(
    bind=test_engine,
    autoflush=False,
    autocommit=False,
)


def override_get_db():
    db = TestSessionLocal()

    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@pytest.fixture
def db():
    db = TestSessionLocal()

    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(autouse=True)
def clean_database():
    db = TestSessionLocal()

    try:
        for table in reversed(Base.metadata.sorted_tables):
            db.execute(delete(table))

        db.commit()
        yield

    finally:
        db.close()


@pytest.fixture
def ready_record(db):
    """A vehicle owned by webhook-owner@example.com with a ready record."""
    owner = User(
        name="Webhook Owner",
        email="webhook-owner@example.com",
        password_hash=hash_password("password123"),
        role="customer",
        email_verified=True,
    )
    db.add(owner)
    db.flush()

    vehicle = Vehicle(
        user_id=owner.id,
        make="Ford",
        model="F-150",
        year=2019,
        vin="WEBHOOKVEHICLE01",
        mileage=12000,
        verified=True,
    )
    db.add(vehicle)
    db.flush()

    record = MaintenanceRecord(
        vehicle_id=vehicle.id,
        service_type="repair",
        description="Brake pads",
        mileage=12000,
        service_date=datetime.now(timezone.utc),
        labor_cost=Decimal("50.00"),
        status="ready",
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    return record


@pytest.fixture
def pending_payment(db, ready_record):
    """The payment waiting for the webhook on that record."""
    payment = Payment(
        maintenance_record_id=ready_record.id,
        amount=Decimal("50.00"),
        currency="usd",
        status="pending",
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)

    return payment


CODE_RE = re.compile(r"<h2>\s*(\d{4,8})\s*</h2>")


class FakeBrevoClient:
    """
    Stand-in for the Brevo SDK client: no real email ever leaves a run.

    The fake sits at the client instead of at each router. Patching per
    module had a hole the moment a third module learned to send email -
    it reached the real service during a test run - so the double lives
    where the process actually touches the outside world.
    """

    def __init__(self, outbox):
        class _TransactionalEmails:
            def send_transac_email(
                self, sender=None, to=None, subject="", html_content="", **kwargs
            ):
                outbox.append(
                    {"to": to[0].email, "subject": subject, "html": html_content}
                )

        self.transactional_emails = _TransactionalEmails()


@pytest.fixture(autouse=True)
def sent_emails(monkeypatch):
    """
    Replace the SMTP boundary: no real email ever leaves a test run.

    The captured outbox doubles as the way to read the verification and 2FA
    codes, so the tests still exercise the real auth flow instead of bypassing
    it. The rate limiter is disabled here because it is a deployment concern
    (5/minute on the auth endpoints) and would make the suite fail randomly.
    """
    outbox = []

    monkeypatch.setattr("app.services.email.client", FakeBrevoClient(outbox))
    monkeypatch.setattr(limiter, "enabled", False)

    return outbox


@pytest.fixture
def accounts(sent_emails):
    """Register, verify, log in and pass 2FA exactly like a real user does."""

    def last_code(email):
        for message in reversed(sent_emails):
            if message["to"] == email:
                match = CODE_RE.search(message["html"])
                if match:
                    return match.group(1)
        raise AssertionError(f"no code was emailed to {email}")

    def verify_email(http, email):
        response = http.post(
            "/users/verify-email",
            json={"email": email, "code": last_code(email)},
        )
        assert response.status_code == 200, response.text

    def register(http, name, email, password="password123"):
        response = http.post(
            "/users/",
            json={
                "name": name,
                "email": email,
                "password": password,
                "password_confirmation": password,
            },
        )
        assert response.status_code == 201, response.text
        verify_email(http, email)

    def login(http, email, password="password123"):
        response = http.post(
            "/users/login",
            data={"username": email, "password": password},
        )
        assert response.status_code == 200, response.text

        response = http.post(
            "/users/verify-2fa",
            json={"email": email, "code": last_code(email)},
        )
        assert response.status_code == 200, response.text
        return response.json()["access_token"]

    return SimpleNamespace(
        register=register,
        login=login,
        verify_email=verify_email,
        last_code=last_code,
    )