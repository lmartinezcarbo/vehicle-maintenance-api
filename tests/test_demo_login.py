"""The public portfolio demo login.

It must be inert unless DEMO_MODE is on, and even then only the three
seeded roles are accepted.
"""

from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.security import hash_password
from app.main import app
from app.models.user import User

client = TestClient(app)

DEMO_EMAIL = "lmartinezcarbo@gmail.com"


def _seeded_demo_user(db, email=DEMO_EMAIL, role="mechanic"):
    user = User(
        name="Demo Mechanic",
        email=email,
        password_hash=hash_password("password123"),
        role=role,
        email_verified=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_demo_availability_is_empty_while_demo_mode_is_off():
    assert settings.demo_mode is False

    response = client.get("/users/demo")

    assert response.status_code == 200
    assert response.json() == {"enabled": False, "roles": []}


def test_demo_login_is_404_while_demo_mode_is_off(db):
    _seeded_demo_user(db)

    response = client.post("/users/demo-login", json={"role": "mechanic"})

    assert response.status_code == 404


def test_demo_availability_lists_roles_in_demo_mode(monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", True)

    response = client.get("/users/demo")

    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is True
    assert set(body["roles"]) == {"customer", "mechanic", "admin"}


def test_demo_login_issues_tokens_in_demo_mode(db, monkeypatch):
    _seeded_demo_user(db)
    monkeypatch.setattr(settings, "demo_mode", True)

    response = client.post("/users/demo-login", json={"role": "mechanic"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["refresh_token"]


def test_demo_login_404s_when_the_seeded_account_is_missing(db, monkeypatch):
    # DEMO_MODE is on, but no such user exists in the database.
    monkeypatch.setattr(settings, "demo_mode", True)

    response = client.post("/users/demo-login", json={"role": "admin"})

    assert response.status_code == 404
