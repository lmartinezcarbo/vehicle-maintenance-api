"""
One answer per endpoint.

Whoever may not touch a resource gets the exact same response - same status
code *and* same detail - whether the resource does not exist, belongs to
somebody else or is simply off limits by role. The real reason is written
to the server log, never to the body.

The deliberate exception: a state hint about something the caller already
owns (their own vehicle) reveals nothing to anybody else, so it stays.
"""

import logging
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.core.security import hash_password
from app.main import app
from app.models import Expense, MaintenancePart, MaintenanceRecord, Part, User, Vehicle

client = TestClient(app)

MISSING_ID = 999999


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def probe(method, path, token, body=None):
    """(status, detail) of a request that must be refused."""
    response = client.request(method, path, json=body, headers=auth(token))
    assert response.status_code == 403, response.text
    return response.status_code, response.json()["detail"]


@pytest.fixture
def owner_token(accounts, ready_record):
    return accounts.login(client, "webhook-owner@example.com")


@pytest.fixture
def other_token(accounts, ready_record):
    accounts.register(client, "Other Customer", "other-uniform@example.com")
    return accounts.login(client, "other-uniform@example.com")


@pytest.fixture
def admin_user(db):
    user = User(
        name="Uniform Admin",
        email="uniform-admin@example.com",
        password_hash=hash_password("password123"),
        role="admin",
        email_verified=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def admin_token(accounts, admin_user):
    return accounts.login(client, "uniform-admin@example.com")


@pytest.fixture
def mechanic_user(db):
    user = User(
        name="Uniform Mechanic",
        email="uniform-mechanic@example.com",
        password_hash=hash_password("password123"),
        role="mechanic",
        email_verified=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def mechanic_token(accounts, mechanic_user):
    return accounts.login(client, "uniform-mechanic@example.com")


def make_vehicle(db, owner, vin, verified=True):
    vehicle = Vehicle(
        user_id=owner.id,
        make="Toyota",
        model="Hilux",
        year=2021,
        vin=vin,
        mileage=50000,
        verified=verified,
    )
    db.add(vehicle)
    db.commit()
    db.refresh(vehicle)
    return vehicle


def make_record(db, vehicle, status="in_progress"):
    record = MaintenanceRecord(
        vehicle_id=vehicle.id,
        service_type="repair",
        description="Uniform probe",
        mileage=50000,
        service_date=datetime.now(timezone.utc),
        labor_cost=Decimal("10.00"),
        status=status,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


@pytest.fixture
def admin_vehicle(db, admin_user):
    """A vehicle no mechanic is allowed to touch (owner is an admin)."""
    return make_vehicle(db, admin_user, "UNIFORMADMINVEH001")


@pytest.fixture
def unverified_admin_vehicle(db, admin_user):
    """Same, but unverified: state must not speak before role."""
    return make_vehicle(db, admin_user, "UNIFORMADMINVEH002", verified=False)


@pytest.fixture
def admin_record(db, admin_vehicle):
    return make_record(db, admin_vehicle)


@pytest.fixture
def part(db):
    part = Part(
        name="Brake pads",
        manufacturer="Bosch",
        part_number="UNIFORM-PROBE-1",
    )
    db.add(part)
    db.commit()
    db.refresh(part)
    return part


@pytest.fixture
def part_on_admin_record(db, admin_record, part):
    row = MaintenancePart(
        maintenance_record_id=admin_record.id,
        part_id=part.id,
        quantity=1,
        unit_cost=Decimal("10.00"),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@pytest.fixture
def part_on_ready_record(db, ready_record, part):
    row = MaintenancePart(
        maintenance_record_id=ready_record.id,
        part_id=part.id,
        quantity=1,
        unit_cost=Decimal("10.00"),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def make_expense(db, record, category="parts"):
    expense = Expense(
        vehicle_id=record.vehicle_id,
        maintenance_record_id=record.id,
        category=category,
        amount=Decimal("5.00"),
        description="Uniform probe",
        expense_date=datetime.now(timezone.utc),
    )
    db.add(expense)
    db.commit()
    db.refresh(expense)
    return expense


@pytest.fixture
def expense_on_ready_record(db, ready_record):
    return make_expense(db, ready_record)


@pytest.fixture
def expense_on_admin_record(db, admin_record):
    return make_expense(db, admin_record)


# --------------------------------------------------------------------------
# Vehicles
# --------------------------------------------------------------------------

def test_a_customer_cannot_tell_vehicles_apart(other_token, ready_record):
    """Foreign vehicle and missing vehicle: byte-identical refusal."""
    foreign = ready_record.vehicle_id
    missing = MISSING_ID

    attempts = (
        ("GET", None),
        ("PATCH", {"make": "Probe"}),
        ("PUT", {"make": "Probe", "model": "Probe", "year": 2020,
                 "vin": "PROBEVEHICLE0001", "mileage": 1}),
        ("DELETE", None),
    )

    for method, body in attempts:
        real = probe(method, f"/vehicles/{foreign}", other_token, body)
        gone = probe(method, f"/vehicles/{missing}", other_token, body)
        assert real == gone, f"{method} /vehicles leaked existence"


def test_a_mechanic_cannot_tell_vehicles_apart(mechanic_token, admin_vehicle):
    """Same for a mechanic, including /verify, which used to answer 404."""
    foreign = admin_vehicle.id
    missing = MISSING_ID

    attempts = (
        ("GET", None),
        ("PATCH", {"make": "Probe"}),
        ("PUT", {"make": "Probe", "model": "Probe", "year": 2020,
                 "vin": "PROBEVEHICLE0002", "mileage": 1}),
        ("DELETE", None),
    )

    for method, body in attempts:
        real = probe(method, f"/vehicles/{foreign}", mechanic_token, body)
        gone = probe(method, f"/vehicles/{missing}", mechanic_token, body)
        assert real == gone, f"{method} /vehicles leaked existence"

    real = probe("PATCH", f"/vehicles/{foreign}/verify", mechanic_token)
    gone = probe("PATCH", f"/vehicles/{missing}/verify", mechanic_token)
    assert real == gone


def test_the_owner_still_gets_a_useful_hint(owner_token, ready_record):
    """A state hint about your *own* vehicle stays: you already know it."""
    response = client.delete(
        f"/vehicles/{ready_record.vehicle_id}", headers=auth(owner_token)
    )

    assert response.status_code == 403
    assert response.json()["detail"] == (
        "Customers can only delete unverified vehicles"
    )


# --------------------------------------------------------------------------
# Maintenance records
# --------------------------------------------------------------------------

def test_a_mechanic_cannot_tell_record_vehicles_apart(
    mechanic_token, admin_vehicle
):
    """Creating a record: existing-but-foreign and missing answer alike."""
    body = {
        "vehicle_id": None,
        "service_type": "repair",
        "description": "Probe",
        "mileage": 1,
        "service_date": "2026-10-04T00:00:00Z",
        "labor_cost": "1.00",
    }

    real = probe(
        "POST",
        "/maintenance-records/",
        mechanic_token,
        {**body, "vehicle_id": admin_vehicle.id},
    )
    gone = probe(
        "POST",
        "/maintenance-records/",
        mechanic_token,
        {**body, "vehicle_id": MISSING_ID},
    )

    assert real == gone


def test_a_status_change_does_not_reveal_existence(
    mechanic_token, admin_record
):
    """PATCH /status answered 404 for a missing record: a yes/no oracle."""
    real = probe(
        "PATCH",
        f"/maintenance-records/{admin_record.id}/status",
        mechanic_token,
        {"status": "ready"},
    )
    gone = probe(
        "PATCH",
        f"/maintenance-records/{MISSING_ID}/status",
        mechanic_token,
        {"status": "ready"},
    )

    assert real == gone
    assert real == (403, "Not authorized to update the status of this "
                         "maintenance record")


def test_the_state_still_speaks_to_the_authorized(
    admin_token, ready_record
):
    """Reordering must not hide the 400 from someone allowed to act."""
    response = client.patch(
        f"/maintenance-records/{ready_record.id}/status",
        json={"status": "ready"},
        headers=auth(admin_token),
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Only maintenance records in progress can be marked as ready"
    )


# --------------------------------------------------------------------------
# Maintenance parts
# --------------------------------------------------------------------------

def test_a_customer_cannot_tell_parts_apart(other_token, part_on_ready_record):
    foreign = part_on_ready_record.id
    missing = MISSING_ID

    attempts = (
        ("GET", None),
        ("PATCH", {"quantity": 2}),
        ("PUT", {"quantity": 2, "unit_cost": "5.00"}),
        ("DELETE", None),
    )

    for method, body in attempts:
        real = probe(
            method, f"/maintenance-part/{foreign}", other_token, body
        )
        gone = probe(
            method, f"/maintenance-part/{missing}", other_token, body
        )
        assert real == gone, f"{method} /maintenance-part leaked existence"


def test_a_mechanic_cannot_tell_parts_apart(
    mechanic_token, part_on_admin_record
):
    foreign = part_on_admin_record.id
    missing = MISSING_ID

    attempts = (
        ("GET", None),
        ("PATCH", {"quantity": 2}),
        ("PUT", {"quantity": 2, "unit_cost": "5.00"}),
        ("DELETE", None),
    )

    for method, body in attempts:
        real = probe(
            method, f"/maintenance-part/{foreign}", mechanic_token, body
        )
        gone = probe(
            method, f"/maintenance-part/{missing}", mechanic_token, body
        )
        assert real == gone, f"{method} /maintenance-part leaked existence"


def test_authorization_speaks_before_state_for_parts(
    db, mechanic_token, part_on_admin_record
):
    """A frozen record on somebody else's vehicle: the outsider must hear
    403 (not their business), never the 400 meant for the allowed."""
    part_on_admin_record.maintenance_record.status = "ready"
    db.commit()

    response = client.patch(
        f"/maintenance-part/{part_on_admin_record.id}",
        json={"quantity": 2},
        headers=auth(mechanic_token),
    )

    assert response.status_code == 403


def test_the_frozen_part_is_still_protected_from_the_allowed(
    admin_token, part_on_ready_record
):
    response = client.patch(
        f"/maintenance-part/{part_on_ready_record.id}",
        json={"quantity": 2},
        headers=auth(admin_token),
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Only records in progress can be modified"


# --------------------------------------------------------------------------
# Expenses
# --------------------------------------------------------------------------

def test_a_customer_cannot_tell_expenses_apart(
    other_token, expense_on_ready_record
):
    foreign = expense_on_ready_record.id
    missing = MISSING_ID

    attempts = (
        ("GET", None),
        ("PATCH", {"amount": "1.00"}),
        ("PUT", {"category": "parts", "amount": "1.00",
                 "expense_date": "2026-10-04T00:00:00Z"}),
        ("DELETE", None),
    )

    for method, body in attempts:
        real = probe(method, f"/expenses/{foreign}", other_token, body)
        gone = probe(method, f"/expenses/{missing}", other_token, body)
        assert real == gone, f"{method} /expenses leaked existence"


def test_a_mechanic_cannot_tell_expenses_apart(
    mechanic_token, expense_on_admin_record
):
    foreign = expense_on_admin_record.id
    missing = MISSING_ID

    attempts = (
        ("GET", None),
        ("PATCH", {"amount": "1.00"}),
        ("PUT", {"category": "parts", "amount": "1.00",
                 "expense_date": "2026-10-04T00:00:00Z"}),
        ("DELETE", None),
    )

    for method, body in attempts:
        real = probe(method, f"/expenses/{foreign}", mechanic_token, body)
        gone = probe(method, f"/expenses/{missing}", mechanic_token, body)
        assert real == gone, f"{method} /expenses leaked existence"


def test_expenses_stop_changing_once_the_record_is_frozen(
    admin_token, expense_on_ready_record
):
    """PATCH/PUT/DELETE used to allow moving the total of a ready record."""
    attempts = (
        ("PATCH", {"amount": "1.00"}),
        ("PUT", {"category": "parts", "amount": "1.00",
                 "expense_date": "2026-10-04T00:00:00Z"}),
        ("DELETE", None),
    )

    for method, body in attempts:
        response = client.request(
            method,
            f"/expenses/{expense_on_ready_record.id}",
            json=body,
            headers=auth(admin_token),
        )
        assert response.status_code == 400, method
        assert response.json()["detail"] == (
            "Only records in progress can be modified"
        )


def test_expense_creation_authorizes_before_it_judges_state(
    mechanic_token, unverified_admin_vehicle
):
    """Unverified *and* somebody else's: the outsider hears 403, not the
    400 meant for people who may actually create the expense."""
    real = probe(
        "POST",
        "/expenses/",
        mechanic_token,
        {
            "vehicle_id": unverified_admin_vehicle.id,
            "category": "parts",
            "amount": "1.00",
            "expense_date": "2026-10-04T00:00:00Z",
        },
    )
    gone = probe(
        "POST",
        "/expenses/",
        mechanic_token,
        {
            "vehicle_id": MISSING_ID,
            "category": "parts",
            "amount": "1.00",
            "expense_date": "2026-10-04T00:00:00Z",
        },
    )

    assert real == gone


# --------------------------------------------------------------------------
# The reason belongs to the log
# --------------------------------------------------------------------------

def test_the_reason_reaches_the_log_not_the_client(
    caplog, other_token, ready_record
):
    with caplog.at_level(logging.WARNING, logger="app.routers.vehicles"):
        client.get(f"/vehicles/{ready_record.vehicle_id}",
                   headers=auth(other_token))

    assert "belongs to" in caplog.text
    assert str(ready_record.vehicle_id) in caplog.text
