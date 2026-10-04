"""
The maintenance job itself.

Vehicle -> verified -> record -> parts and expenses -> ready, plus every
door that must be closed once it is ready. The endpoints existed; the
status codes of a refused write and the money they add up to had no test
behind them.
"""

import logging
import re
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.core.security import hash_password
from app.main import app
from app.models import User

client = TestClient(app)


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def money(value):
    """Totals arrive as JSON numbers; never compare them with ==."""
    return Decimal(str(value)).quantize(Decimal("0.01"))


@pytest.fixture
def owner_token(accounts, db):
    accounts.register(client, "Lifecycle Owner", "lifecycle-owner@example.com")
    return accounts.login(client, "lifecycle-owner@example.com")


@pytest.fixture
def intruder_token(accounts, db):
    accounts.register(client, "Lifecycle Intruder", "lifecycle-intruder@example.com")
    return accounts.login(client, "lifecycle-intruder@example.com")


@pytest.fixture
def admin_token(accounts, db):
    db.add(
        User(
            name="Lifecycle Admin",
            email="lifecycle-admin@example.com",
            password_hash=hash_password("password123"),
            role="admin",
            email_verified=True,
        )
    )
    db.commit()
    return accounts.login(client, "lifecycle-admin@example.com")


@pytest.fixture
def mechanic_token(accounts, db):
    db.add(
        User(
            name="Lifecycle Mechanic",
            email="lifecycle-mechanic@example.com",
            password_hash=hash_password("password123"),
            role="mechanic",
            email_verified=True,
        )
    )
    db.commit()
    return accounts.login(client, "lifecycle-mechanic@example.com")


@pytest.fixture
def job(owner_token, admin_token, mechanic_token):
    """An open job, built through the API the way it happens in real life."""
    vehicle = client.post(
        "/vehicles/",
        json={"make": "Toyota", "model": "Corolla", "year": 2020,
              "vin": "LIFECYCLEVEHICLE1", "mileage": 10000},
        headers=auth(owner_token),
    )
    assert vehicle.status_code == 201, vehicle.text
    vehicle_id = vehicle.json()["id"]

    verified = client.patch(
        f"/vehicles/{vehicle_id}/verify", headers=auth(mechanic_token)
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["verified"] is True

    catalog_part = client.post(
        "/parts/",
        json={"name": "Brake pads", "manufacturer": "Bosch",
              "part_number": "LIFECYCLE-1"},
        headers=auth(admin_token),
    )
    assert catalog_part.status_code == 201, catalog_part.text

    record = client.post(
        "/maintenance-records/",
        json={"vehicle_id": vehicle_id, "service_type": "repair",
              "description": "Front brakes", "mileage": 10500,
              "service_date": "2026-10-01T00:00:00Z",
              "labor_cost": "80.00"},
        headers=auth(mechanic_token),
    )
    assert record.status_code == 201, record.text
    assert record.json()["status"] == "in_progress"

    return {
        "vehicle_id": vehicle_id,
        "record_id": record.json()["id"],
        "part_id": catalog_part.json()["id"],
    }


# --------------------------------------------------------------------------
# The happy path, with the arithmetic checked
# --------------------------------------------------------------------------

def test_a_maintenance_job_follows_the_money(
    job, mechanic_token, owner_token
):
    labor = Decimal("80.00")
    parts = Decimal("2") * Decimal("15.00")
    expense = Decimal("12.50")

    added = client.post(
        "/maintenance-part/",
        json={"maintenance_record_id": job["record_id"],
              "part_id": job["part_id"], "quantity": 2,
              "unit_cost": "15.00"},
        headers=auth(mechanic_token),
    )
    assert added.status_code == 201, added.text

    charged = client.get(
        f"/maintenance-records/{job['record_id']}",
        headers=auth(owner_token),
    )
    assert charged.status_code == 200, charged.text
    assert money(charged.json()["total_cost"]) == labor + parts

    spent = client.post(
        "/expenses/",
        json={"vehicle_id": job["vehicle_id"],
              "maintenance_record_id": job["record_id"],
              "category": "fuel", "amount": str(expense),
              "expense_date": "2026-10-02T00:00:00Z"},
        headers=auth(mechanic_token),
    )
    assert spent.status_code == 201, spent.text

    # Expenses are workshop bookkeeping: the charge is labor + parts.
    still = client.get(
        f"/maintenance-records/{job['record_id']}",
        headers=auth(owner_token),
    )
    assert money(still.json()["total_cost"]) == labor + parts


def test_ready_shuts_every_door(job, mechanic_token, admin_token):
    ready = client.patch(
        f"/maintenance-records/{job['record_id']}/status",
        json={"status": "ready"},
        headers=auth(mechanic_token),
    )
    assert ready.status_code == 200, ready.text
    assert ready.json()["status"] == "ready"

    frozen = (
        ("POST", "/maintenance-part/",
         {"maintenance_record_id": job["record_id"],
          "part_id": job["part_id"], "quantity": 1, "unit_cost": "1.00"}),
        ("POST", "/expenses/",
         {"vehicle_id": job["vehicle_id"],
          "maintenance_record_id": job["record_id"],
          "category": "fuel", "amount": "1.00",
          "expense_date": "2026-10-02T00:00:00Z"}),
        ("PATCH", f"/maintenance-records/{job['record_id']}",
         {"labor_cost": "1.00"}),
        ("DELETE", f"/maintenance-records/{job['record_id']}", None),
        ("PATCH", f"/maintenance-records/{job['record_id']}/status",
         {"status": "ready"}),
    )

    for method, path, body in frozen:
        response = client.request(
            method, path, json=body, headers=auth(admin_token)
        )
        assert response.status_code == 400, f"{method} {path}: {response.text}"


def test_an_open_record_can_be_deleted(job, admin_token):
    response = client.delete(
        f"/maintenance-records/{job['record_id']}",
        headers=auth(admin_token),
    )

    assert response.status_code == 200
    assert client.get(
        f"/maintenance-records/{job['record_id']}",
        headers=auth(admin_token),
    ).status_code == 403


def test_mileage_cannot_move_backwards(job, mechanic_token):
    response = client.post(
        "/maintenance-records/",
        # Later in time than the first visit, but with fewer kilometres:
        # the guard compares against the previous service_date.
        json={"vehicle_id": job["vehicle_id"], "service_type": "repair",
              "description": "Clock rolled back", "mileage": 50,
              "service_date": "2026-10-05T00:00:00Z",
              "labor_cost": "10.00"},
        headers=auth(mechanic_token),
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Maintenance mileage cannot be lower than the previous "
        "maintenance mileage"
    )


# --------------------------------------------------------------------------
# Scoping: what somebody else is allowed to even see
# --------------------------------------------------------------------------

def test_records_belong_to_the_owner(job, intruder_token):
    listing = client.get(
        "/maintenance-records/", headers=auth(intruder_token)
    )
    assert listing.status_code == 200
    assert job["record_id"] not in [
        record["id"] for record in listing.json()
    ]

    detail = client.get(
        f"/maintenance-records/{job['record_id']}",
        headers=auth(intruder_token),
    )
    assert detail.status_code == 403


def test_parts_and_expenses_belong_to_the_owner(
    job, intruder_token, mechanic_token
):
    client.post(
        "/maintenance-part/",
        json={"maintenance_record_id": job["record_id"],
              "part_id": job["part_id"], "quantity": 1,
              "unit_cost": "15.00"},
        headers=auth(mechanic_token),
    )
    client.post(
        "/expenses/",
        json={"vehicle_id": job["vehicle_id"],
              "maintenance_record_id": job["record_id"],
              "category": "fuel", "amount": "9.00",
              "expense_date": "2026-10-02T00:00:00Z"},
        headers=auth(mechanic_token),
    )

    parts = client.get(
        "/maintenance-part/", headers=auth(intruder_token)
    )
    assert parts.status_code == 200
    assert parts.json() == []

    expenses = client.get("/expenses/", headers=auth(intruder_token))
    assert expenses.status_code == 200
    assert expenses.json() == []


def test_the_parts_catalog_is_admin_only(job, owner_token):
    response = client.post(
        "/parts/",
        json={"name": "Filter", "manufacturer": "Mann",
              "part_number": "LIFECYCLE-2"},
        headers=auth(owner_token),
    )

    assert response.status_code == 403


# --------------------------------------------------------------------------
# Deletions are attributable
# --------------------------------------------------------------------------

def test_a_successful_delete_leaves_a_trace_in_the_log(
    caplog, job, admin_token
):
    """When a row disappears, the log has to say which one and who did it.

    This is what turns "the rows vanished" into an answer: the resource
    id, the user id and the fact that the delete succeeded.
    """
    with caplog.at_level(
        logging.INFO, logger="app.routers.maintenance_records"
    ), caplog.at_level(logging.INFO, logger="app.routers.vehicles"):
        record = client.delete(
            f"/maintenance-records/{job['record_id']}",
            headers=auth(admin_token),
        )
        vehicle = client.delete(
            f"/vehicles/{job['vehicle_id']}",
            headers=auth(admin_token),
        )

    assert record.status_code == 200
    assert vehicle.status_code == 200

    assert re.search(
        rf"maintenance record {job['record_id']} deleted \(user \d+\)",
        caplog.text,
    )
    assert re.search(
        rf"vehicle {job['vehicle_id']} deleted \(user \d+\)", caplog.text
    )
