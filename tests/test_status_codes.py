"""
Status codes for the state of the world.

- 201: the server created a resource
- 409: the request collided with data that already exists or still
  references something (foreign keys, unique constraints)
- 422: the payload could never be stored (CHECK constraints, columns out
  of range)

None of these used to be reachable: constraint violations fell through to
a 500 (or to a raised exception), and creations answered 200.
"""

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.core.security import hash_password
from app.main import app
from app.models import (
    MaintenancePart,
    MaintenanceRecord,
    Part,
    User,
    Vehicle,
)

client = TestClient(app)


def auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_user(db):
    user = User(
        name="Status Admin",
        email="status-admin@example.com",
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
    return accounts.login(client, "status-admin@example.com")


@pytest.fixture
def worker(db):
    """A customer, a verified vehicle, an open record and a part.

    Enough real data to collide with foreign keys, unique constraints and
    CHECK constraints on demand.
    """
    owner = User(
        name="Status Owner",
        email="status-owner@example.com",
        password_hash=hash_password("password123"),
        role="customer",
        email_verified=True,
    )
    db.add(owner)
    db.flush()

    vehicle = Vehicle(
        user_id=owner.id,
        make="Ford",
        model="Focus",
        year=2018,
        vin="STATUSCODEVEH001",
        mileage=90000,
        verified=True,
    )
    db.add(vehicle)
    db.flush()

    record = MaintenanceRecord(
        vehicle_id=vehicle.id,
        service_type="inspection",
        description="Status codes",
        mileage=90000,
        service_date=datetime.now(timezone.utc),
        labor_cost=Decimal("20.00"),
        status="in_progress",
    )
    db.add(record)
    db.flush()

    part = Part(
        name="Oil filter",
        manufacturer="Mann",
        part_number="STATUS-CODE-1",
    )
    db.add(part)
    db.commit()

    for row in (owner, vehicle, record, part):
        db.refresh(row)

    return SimpleNamespace(
        owner=owner, vehicle=vehicle, record=record, part=part
    )


# --------------------------------------------------------------------------
# 201: a resource was created
# --------------------------------------------------------------------------

def test_creating_a_part_is_201(admin_token):
    response = client.post(
        "/parts/",
        json={"name": "Spark plug", "manufacturer": "Bosch",
              "part_number": "STATUS-SPARK-1"},
        headers=auth(admin_token),
    )

    assert response.status_code == 201


def test_creating_a_vehicle_is_201(admin_token, worker):
    response = client.post(
        "/vehicles/",
        json={"user_id": worker.owner.id, "make": "Toyota", "model": "Corolla",
              "year": 2020, "vin": "STATUSCODEVEH002", "mileage": 10},
        headers=auth(admin_token),
    )

    assert response.status_code == 201


def test_creating_a_maintenance_record_is_201(admin_token, worker):
    response = client.post(
        "/maintenance-records/",
        json={"vehicle_id": worker.vehicle.id, "service_type": "repair",
              "description": "Status codes", "mileage": 90001,
              "service_date": "2026-10-04T00:00:00Z", "labor_cost": "1.00"},
        headers=auth(admin_token),
    )

    assert response.status_code == 201


def test_creating_an_expense_is_201(admin_token, worker):
    response = client.post(
        "/expenses/",
        json={"vehicle_id": worker.vehicle.id,
              "maintenance_record_id": worker.record.id,
              "category": "fuel", "amount": "5.00",
              "expense_date": "2026-10-04T00:00:00Z"},
        headers=auth(admin_token),
    )

    assert response.status_code == 201


def test_creating_a_maintenance_part_is_201(admin_token, worker):
    response = client.post(
        "/maintenance-part/",
        json={"maintenance_record_id": worker.record.id,
              "part_id": worker.part.id, "quantity": 1,
              "unit_cost": "3.50"},
        headers=auth(admin_token),
    )

    assert response.status_code == 201


# --------------------------------------------------------------------------
# 409: the request collided with existing data
# --------------------------------------------------------------------------

def test_deleting_a_vehicle_with_records_conflicts(admin_token, worker):
    response = client.delete(
        f"/vehicles/{worker.vehicle.id}", headers=auth(admin_token)
    )

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "The resource is still referenced by other data"
    )

    # The failed transaction did not poison the connection: the next
    # request still gets an answer.
    assert client.get("/vehicles/", headers=auth(admin_token)).status_code == 200


def test_deleting_a_user_with_vehicles_conflicts(admin_token, worker):
    response = client.delete(
        f"/users/{worker.owner.id}", headers=auth(admin_token)
    )

    assert response.status_code == 409


def test_deleting_a_part_in_use_conflicts(admin_token, worker):
    client.post(
        "/maintenance-part/",
        json={"maintenance_record_id": worker.record.id,
              "part_id": worker.part.id, "quantity": 1,
              "unit_cost": "3.50"},
        headers=auth(admin_token),
    )

    response = client.delete(
        f"/parts/{worker.part.id}", headers=auth(admin_token)
    )

    assert response.status_code == 409


def test_a_repeated_vin_conflicts(admin_token, worker):
    response = client.post(
        "/vehicles/",
        json={"user_id": worker.owner.id, "make": "Ford", "model": "Focus",
              "year": 2018, "vin": worker.vehicle.vin, "mileage": 1},
        headers=auth(admin_token),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "That resource already exists"


def test_a_repeated_part_conflicts(admin_token):
    body = {"name": "Oil filter", "manufacturer": "Mann",
            "part_number": "STATUS-DUP-1"}
    assert client.post("/parts/", json=body, headers=auth(admin_token)).status_code == 201

    response = client.post("/parts/", json=body, headers=auth(admin_token))

    assert response.status_code == 409
    assert response.json()["detail"] == "That resource already exists"


def test_the_same_part_twice_on_one_record_conflicts(admin_token, worker):
    body = {"maintenance_record_id": worker.record.id,
            "part_id": worker.part.id, "quantity": 1, "unit_cost": "3.50"}
    assert client.post(
        "/maintenance-part/", json=body, headers=auth(admin_token)
    ).status_code == 201

    response = client.post(
        "/maintenance-part/", json=body, headers=auth(admin_token)
    )

    assert response.status_code == 409


# --------------------------------------------------------------------------
# 422: the payload could never be stored
# --------------------------------------------------------------------------

def test_a_negative_mileage_is_unprocessable(admin_token, worker):
    response = client.post(
        "/maintenance-records/",
        json={"vehicle_id": worker.vehicle.id, "service_type": "repair",
              "description": "Backwards", "mileage": -1,
              "service_date": "2026-10-04T00:00:00Z", "labor_cost": "1.00"},
        headers=auth(admin_token),
    )

    # 422 either way; now the schema rejects it before the database does,
    # so the detail is Pydantic's and points at the offending field.
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "mileage"]


def test_a_negative_expense_amount_is_unprocessable(admin_token, worker):
    response = client.post(
        "/expenses/",
        json={"vehicle_id": worker.vehicle.id,
              "maintenance_record_id": worker.record.id,
              "category": "fuel", "amount": "-5.00",
              "expense_date": "2026-10-04T00:00:00Z"},
        headers=auth(admin_token),
    )

    assert response.status_code == 422


def test_a_zero_quantity_is_unprocessable(admin_token, worker):
    response = client.post(
        "/maintenance-part/",
        json={"maintenance_record_id": worker.record.id,
              "part_id": worker.part.id, "quantity": 0,
              "unit_cost": "3.50"},
        headers=auth(admin_token),
    )

    assert response.status_code == 422


def test_an_out_of_range_integer_is_unprocessable(admin_token, worker):
    """Postgres 'integer out of range' (a DataError), not a crash."""
    response = client.post(
        "/maintenance-records/",
        json={"vehicle_id": worker.vehicle.id, "service_type": "repair",
              "description": "Too far", "mileage": 10 ** 12,
              "service_date": "2026-10-04T00:00:00Z", "labor_cost": "1.00"},
        headers=auth(admin_token),
    )

    assert response.status_code == 422


def test_a_creation_that_collided_still_allows_the_next_request(
    admin_token, worker
):
    """A 422/409 must leave the session clean: the next write works."""
    bad = client.post(
        "/maintenance-records/",
        json={"vehicle_id": worker.vehicle.id, "service_type": "repair",
              "description": "Nope", "mileage": -1,
              "service_date": "2026-10-04T00:00:00Z", "labor_cost": "1.00"},
        headers=auth(admin_token),
    )
    assert bad.status_code == 422

    good = client.post(
        "/maintenance-records/",
        json={"vehicle_id": worker.vehicle.id, "service_type": "repair",
              "description": "Fine", "mileage": 90002,
              "service_date": "2026-10-04T00:00:00Z", "labor_cost": "1.00"},
        headers=auth(admin_token),
    )
    assert good.status_code == 201
