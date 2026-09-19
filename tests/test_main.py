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


def test_login():
    client.post(
        "/users/",
        json={
            "name": "Login User",
            "email": "login-test@example.com",
            "password": "password123",
        },
    )

    response = client.post(
        "/users/login",
        data={
            "username": "login-test@example.com",
            "password": "password123",
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert "access_token" in data
    assert data["token_type"] == "bearer"


def test_get_current_user_without_token():
    response = client.get("/users/me")

    assert response.status_code == 401


def test_get_current_user_with_token():
    client.post(
        "/users/",
        json={
            "name": "Authenticated User",
            "email": "auth-test@example.com",
            "password": "password123",
        },
    )

    login_response = client.post(
        "/users/login",
        data={
            "username": "auth-test@example.com",
            "password": "password123",
        },
    )

    token = login_response.json()["access_token"]

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


def test_create_vehicle():
    client.post(
        "/users/",
        json={
            "name": "Vehicle Owner",
            "email": "vehicle-owner@example.com",
            "password": "password123",
        },
    )

    login_response = client.post(
        "/users/login",
        data={
            "username": "vehicle-owner@example.com",
            "password": "password123",
        },
    )

    token = login_response.json()["access_token"]

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


def test_user_cannot_access_another_users_vehicle():
    # Crear usuario 1
    client.post(
        "/users/",
        json={
            "name": "Owner One",
            "email": "owner-one@example.com",
            "password": "password123",
        },
    )

    login_one = client.post(
        "/users/login",
        data={
            "username": "owner-one@example.com",
            "password": "password123",
        },
    )

    token_one = login_one.json()["access_token"]

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
    client.post(
        "/users/",
        json={
            "name": "Owner Two",
            "email": "owner-two@example.com",
            "password": "password123",
        },
    )

    login_two = client.post(
        "/users/login",
        data={
            "username": "owner-two@example.com",
            "password": "password123",
        },
    )

    token_two = login_two.json()["access_token"]

    # Usuario 2 intenta acceder al vehículo del usuario 1
    response = client.get(
        f"/vehicles/{vehicle_id}",
        headers={
            "Authorization": f"Bearer {token_two}"
        },
    )

    assert response.status_code == 403

    assert response.json()["detail"] == "Not authorized to access this vehicle"


def test_user_can_access_own_vehicle():
    client.post(
        "/users/",
        json={
            "name": "Vehicle Owner",
            "email": "own-vehicle@example.com",
            "password": "password123",
        },
    )

    login_response = client.post(
        "/users/login",
        data={
            "username": "own-vehicle@example.com",
            "password": "password123",
        },
    )

    token = login_response.json()["access_token"]

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


def test_admin_can_access_another_users_vehicle(db):
    # Crear usuario normal
    client.post(
        "/users/",
        json={
            "name": "Vehicle Owner",
            "email": "admin-test-owner@example.com",
            "password": "password123",
        },
    )

    login_owner = client.post(
        "/users/login",
        data={
            "username": "admin-test-owner@example.com",
            "password": "password123",
        },
    )

    owner_token = login_owner.json()["access_token"]

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
    admin = User(
        name="Admin User",
        email="admin-test@example.com",
        password_hash=hash_password("password123"),
        role="admin",
    )

    db.add(admin)
    db.commit()
    db.refresh(admin)

    login_admin = client.post(
    "/users/login",
        data={
            "username": "admin-test@example.com",
            "password": "password123",
        },
    )

    assert login_admin.status_code == 200

    admin_token = login_admin.json()["access_token"]

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

def test_user_cannot_update_another_users_vehicle():
    client.post(
        "/users/",
        json={
            "name": "Owner One",
            "email": "update-owner-one@example.com",
            "password": "password123",
        },
    )

    login_one = client.post(
        "/users/login",
        data={
            "username": "update-owner-one@example.com",
            "password": "password123",
        },
    )

    token_one = login_one.json()["access_token"]

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

    client.post(
        "/users/",
        json={
            "name": "Owner Two",
            "email": "update-owner-two@example.com",
            "password": "password123",
        },
    )

    login_two = client.post(
        "/users/login",
        data={
            "username": "update-owner-two@example.com",
            "password": "password123",
        },
    )

    token_two = login_two.json()["access_token"]

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

def test_user_can_update_own_vehicle():
    client.post(
        "/users/",
        json={
            "name": "Vehicle Owner",
            "email": "update-own@example.com",
            "password": "password123",
        },
    )

    login_response = client.post(
        "/users/login",
        data={
            "username": "update-own@example.com",
            "password": "password123",
        },
    )

    token = login_response.json()["access_token"]

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

def test_user_cannot_delete_another_users_vehicle():
    client.post(
        "/users/",
        json={
            "name": "Owner One",
            "email": "delete-owner-one@example.com",
            "password": "password123",
        },
    )

    login_one = client.post(
        "/users/login",
        data={
            "username": "delete-owner-one@example.com",
            "password": "password123",
        },
    )

    token_one = login_one.json()["access_token"]

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

    client.post(
        "/users/",
        json={
            "name": "Owner Two",
            "email": "delete-owner-two@example.com",
            "password": "password123",
        },
    )

    login_two = client.post(
        "/users/login",
        data={
            "username": "delete-owner-two@example.com",
            "password": "password123",
        },
    )

    token_two = login_two.json()["access_token"]

    response = client.delete(
        f"/vehicles/{vehicle_id}",
        headers={
            "Authorization": f"Bearer {token_two}"
        },
    )

    assert response.status_code == 403

def test_user_can_delete_own_vehicle():
    client.post(
        "/users/",
        json={
            "name": "Delete Owner",
            "email": "delete-own@example.com",
            "password": "password123",
        },
    )

    login_response = client.post(
        "/users/login",
        data={
            "username": "delete-own@example.com",
            "password": "password123",
        },
    )

    token = login_response.json()["access_token"]

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

    assert response.status_code == 404

def test_create_vehicle_with_negative_mileage():
    client.post(
        "/users/",
        json={
            "name": "Validation User",
            "email": "validation-user@example.com",
            "password": "password123",
        },
    )

    login_response = client.post(
        "/users/login",
        data={
            "username": "validation-user@example.com",
            "password": "password123",
        },
    )

    token = login_response.json()["access_token"]

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

def test_update_vehicle_with_negative_mileage():
    client.post(
        "/users/",
        json={
            "name": "Update Validation User",
            "email": "update-validation@example.com",
            "password": "password123",
        },
    )

    login_response = client.post(
        "/users/login",
        data={
            "username": "update-validation@example.com",
            "password": "password123",
        },
    )

    token = login_response.json()["access_token"]

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

def test_create_vehicle_with_invalid_mileage_type():
    client.post(
        "/users/",
        json={
            "name": "Type Validation User",
            "email": "type-validation@example.com",
            "password": "password123",
        },
    )

    login_response = client.post(
        "/users/login",
        data={
            "username": "type-validation@example.com",
            "password": "password123",
        },
    )

    token = login_response.json()["access_token"]

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


def test_update_vehicle_with_invalid_mileage_type():
    client.post(
        "/users/",
        json={
            "name": "Update Type User",
            "email": "update-type@example.com",
            "password": "password123",
        },
    )

    login_response = client.post(
        "/users/login",
        data={
            "username": "update-type@example.com",
            "password": "password123",
        },
    )

    token = login_response.json()["access_token"]

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