from fastapi.testclient import TestClient
from sqlalchemy import text

from app.models.user import User
from app.core.security import hash_password
from app.main import app

client = TestClient(app)


def test_root():
    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {
        "message": "Welcome to the Vehicle Maintenance API!"
    }


def test_create_user():
    response = client.post(
        "/users/",
        json={
            "name": "Test User",
            "email": "1pytest-user-001@example.com",
            "password": "password123",
            "password_confirmation": "password123",
        },
    )

    assert response.status_code == 201

    data = response.json()

    assert data["name"] == "Test User"
    assert data["email"] == "1pytest-user-001@example.com"
    assert "password" not in data
    assert "password_hash" not in data


def test_database_connection(db):
    result = db.execute(text("SELECT 1"))

    assert result.scalar() == 1


def test_login(accounts):
    accounts.register(client, "Login User", "login-test@example.com")

    response = client.post(
        "/users/login",
        data={
            "username": "login-test@example.com",
            "password": "password123",
        },
    )

    assert response.status_code == 200

    data = response.json()

    # Login does not grant a token: it issues a 2FA challenge first.
    assert data["requires_2fa"] is True
    assert "access_token" not in data

    # The emailed code is what finally grants the token.
    token = accounts.login(client, "login-test@example.com")

    assert token


def test_get_current_user_without_token():
    response = client.get("/users/me")

    assert response.status_code == 401


def test_get_current_user_with_token(accounts):
    accounts.register(client, "Authenticated User", "auth-test@example.com")
    token = accounts.login(client, "auth-test@example.com")

    response = client.get(
        "/users/me",
        headers={
            "Authorization": f"Bearer {token}"
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert data["email"] == "auth-test@example.com"
    assert data["name"] == "Authenticated User"


def test_create_vehicle(accounts):
    accounts.register(client, "Vehicle Owner", "vehicle-owner@example.com")
    token = accounts.login(client, "vehicle-owner@example.com")

    response = client.post(
        "/vehicles/",
        headers={
            "Authorization": f"Bearer {token}"
        },
        json={
            "make": "Ford",
            "model": "F-150",
            "year": 2017,
            "vin": "1FTFW1E50HFA12345",
            "mileage": 134000,
        },
    )

    assert response.status_code == 201

    data = response.json()

    assert data["make"] == "Ford"
    assert data["model"] == "F-150"
    assert data["year"] == 2017
    assert data["vin"] == "1FTFW1E50HFA12345"
    assert data["mileage"] == 134000


def test_user_cannot_access_another_users_vehicle(accounts):
    # Crear usuario 1
    accounts.register(client, "Owner One", "owner-one@example.com")
    token_one = accounts.login(client, "owner-one@example.com")

    # Crear vehículo del usuario 1
    vehicle_response = client.post(
        "/vehicles/",
        headers={
            "Authorization": f"Bearer {token_one}"
        },
        json={
            "make": "Ford",
            "model": "F-150",
            "year": 2017,
            "vin": "TESTVIN0000000001",
            "mileage": 134000,
        },
    )

    vehicle_id = vehicle_response.json()["id"]

    # Crear usuario 2
    accounts.register(client, "Owner Two", "owner-two@example.com")
    token_two = accounts.login(client, "owner-two@example.com")

    # Usuario 2 intenta acceder al vehículo del usuario 1
    response = client.get(
        f"/vehicles/{vehicle_id}",
        headers={
            "Authorization": f"Bearer {token_two}"
        },
    )

    assert response.status_code == 403

    assert response.json()["detail"] == "Not authorized to access this vehicle"


def test_user_can_access_own_vehicle(accounts):
    accounts.register(client, "Vehicle Owner", "own-vehicle@example.com")
    token = accounts.login(client, "own-vehicle@example.com")

    vehicle_response = client.post(
        "/vehicles/",
        headers={
            "Authorization": f"Bearer {token}"
        },
        json={
            "make": "Ford",
            "model": "F-150",
            "year": 2017,
            "vin": "OWNVEHICLE00000001",
            "mileage": 134000,
        },
    )

    vehicle_id = vehicle_response.json()["id"]

    response = client.get(
        f"/vehicles/{vehicle_id}",
        headers={
            "Authorization": f"Bearer {token}"
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert data["id"] == vehicle_id
    assert data["make"] == "Ford"
    assert data["model"] == "F-150"


def test_admin_can_access_another_users_vehicle(db, accounts):
    # Crear usuario normal
    accounts.register(client, "Vehicle Owner", "admin-test-owner@example.com")
    owner_token = accounts.login(client, "admin-test-owner@example.com")

    # Crear vehículo del usuario normal
    vehicle_response = client.post(
        "/vehicles/",
        headers={
            "Authorization": f"Bearer {owner_token}"
        },
        json={
            "make": "Toyota",
            "model": "Tacoma",
            "year": 2020,
            "vin": "ADMINTEST00000001",
            "mileage": 80000,
        },
    )

    vehicle_id = vehicle_response.json()["id"]

    # Crear admin directamente en la BD de test
    # email_verified=True: direct inserts bypass the registration flow, and
    # the login endpoint refuses unverified emails.
    admin = User(
        name="Admin User",
        email="admin-test@example.com",
        password_hash=hash_password("password123"),
        role="admin",
        email_verified=True,
    )

    db.add(admin)
    db.commit()
    db.refresh(admin)

    admin_token = accounts.login(client, "admin-test@example.com")

    response = client.get(
    f"/vehicles/{vehicle_id}",
        headers={
            "Authorization": f"Bearer {admin_token}"
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert data["id"] == vehicle_id
    assert data["make"] == "Toyota"
    assert data["model"] == "Tacoma"

def test_user_cannot_update_another_users_vehicle(accounts):
    accounts.register(client, "Owner One", "update-owner-one@example.com")
    token_one = accounts.login(client, "update-owner-one@example.com")

    vehicle_response = client.post(
        "/vehicles/",
        headers={
            "Authorization": f"Bearer {token_one}"
        },
        json={
            "make": "Ford",
            "model": "F-150",
            "year": 2017,
            "vin": "UPDATEVEHICLE00001",
            "mileage": 134000,
        },
    )

    vehicle_id = vehicle_response.json()["id"]

    accounts.register(client, "Owner Two", "update-owner-two@example.com")
    token_two = accounts.login(client, "update-owner-two@example.com")

    response = client.patch(
        f"/vehicles/{vehicle_id}",
        headers={
            "Authorization": f"Bearer {token_two}"
        },
        json={
            "mileage": 150000
        },
    )

    assert response.status_code == 403

def test_user_can_update_own_vehicle(accounts):
    accounts.register(client, "Vehicle Owner", "update-own@example.com")
    token = accounts.login(client, "update-own@example.com")

    vehicle_response = client.post(
        "/vehicles/",
        headers={
            "Authorization": f"Bearer {token}"
        },
        json={
            "make": "Ford",
            "model": "F-150",
            "year": 2017,
            "vin": "UPDATEOWNVEHICLE01",
            "mileage": 134000,
        },
    )

    vehicle_id = vehicle_response.json()["id"]

    response = client.patch(
        f"/vehicles/{vehicle_id}",
        headers={
            "Authorization": f"Bearer {token}"
        },
        json={
            "mileage": 150000
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert data["id"] == vehicle_id
    assert data["mileage"] == 150000

def test_user_cannot_delete_another_users_vehicle(accounts):
    accounts.register(client, "Owner One", "delete-owner-one@example.com")
    token_one = accounts.login(client, "delete-owner-one@example.com")

    vehicle_response = client.post(
        "/vehicles/",
        headers={
            "Authorization": f"Bearer {token_one}"
        },
        json={
            "make": "Ford",
            "model": "F-150",
            "year": 2017,
            "vin": "DELETEVEHICLE00001",
            "mileage": 134000,
        },
    )

    vehicle_id = vehicle_response.json()["id"]

    accounts.register(client, "Owner Two", "delete-owner-two@example.com")
    token_two = accounts.login(client, "delete-owner-two@example.com")

    response = client.delete(
        f"/vehicles/{vehicle_id}",
        headers={
            "Authorization": f"Bearer {token_two}"
        },
    )

    assert response.status_code == 403

def test_user_can_delete_own_vehicle(accounts):
    accounts.register(client, "Delete Owner", "delete-own@example.com")
    token = accounts.login(client, "delete-own@example.com")

    vehicle_response = client.post(
        "/vehicles/",
        headers={
            "Authorization": f"Bearer {token}"
        },
        json={
            "make": "Ford",
            "model": "F-150",
            "year": 2017,
            "vin": "DELETEOWNVEHICLE01",
            "mileage": 134000,
        },
    )

    vehicle_id = vehicle_response.json()["id"]

    response = client.delete(
        f"/vehicles/{vehicle_id}",
        headers={
            "Authorization": f"Bearer {token}"
        },
    )

    assert response.status_code == 200

    response = client.get(
        f"/vehicles/{vehicle_id}",
        headers={
            "Authorization": f"Bearer {token}"
        },
    )

    # 403 is deliberate: a missing vehicle must be indistinguishable from
    # one that belongs to someone else, so no one can probe which IDs exist.
    assert response.status_code == 403

def test_create_vehicle_with_negative_mileage(accounts):
    accounts.register(client, "Validation User", "validation-user@example.com")
    token = accounts.login(client, "validation-user@example.com")

    response = client.post(
        "/vehicles/",
        headers={
            "Authorization": f"Bearer {token}"
        },
        json={
            "make": "Ford",
            "model": "F-150",
            "year": 2017,
            "vin": "VALIDATIONVEHICLE01",
            "mileage": -100,
        },
    )

    assert response.status_code == 422

def test_update_vehicle_with_negative_mileage(accounts):
    accounts.register(
        client, "Update Validation User", "update-validation@example.com"
    )
    token = accounts.login(client, "update-validation@example.com")

    vehicle_response = client.post(
        "/vehicles/",
        headers={
            "Authorization": f"Bearer {token}"
        },
        json={
            "make": "Ford",
            "model": "F-150",
            "year": 2017,
            "vin": "UPDATEVALIDATION01",
            "mileage": 134000,
        },
    )

    vehicle_id = vehicle_response.json()["id"]

    response = client.patch(
        f"/vehicles/{vehicle_id}",
        headers={
            "Authorization": f"Bearer {token}"
        },
        json={
            "mileage": -500,
        },
    )

    assert response.status_code == 422

def test_create_vehicle_with_invalid_mileage_type(accounts):
    accounts.register(client, "Type Validation User", "type-validation@example.com")
    token = accounts.login(client, "type-validation@example.com")

    response = client.post(
        "/vehicles/",
        headers={
            "Authorization": f"Bearer {token}"
        },
        json={
            "make": "Ford",
            "model": "F-150",
            "year": 2017,
            "vin": "INVALIDTYPEVEH01",
            "mileage": "abc",
        },
    )

    assert response.status_code == 422


def test_update_vehicle_with_invalid_mileage_type(accounts):
    accounts.register(client, "Update Type User", "update-type@example.com")
    token = accounts.login(client, "update-type@example.com")

    vehicle_response = client.post(
        "/vehicles/",
        headers={
            "Authorization": f"Bearer {token}"
        },
        json={
            "make": "Ford",
            "model": "F-150",
            "year": 2017,
            "vin": "UPDATETYPEVEH01",
            "mileage": 134000,
        },
    )

    vehicle_id = vehicle_response.json()["id"]

    response = client.patch(
        f"/vehicles/{vehicle_id}",
        headers={
            "Authorization": f"Bearer {token}"
        },
        json={
            "mileage": "abc",
        },
    )

    assert response.status_code == 422