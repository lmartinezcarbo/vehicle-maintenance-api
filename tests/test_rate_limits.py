"""
The four endpoints that rewrite a user account.

Authentication always had a limit (5/minute); these four had none, so a
single stolen token could hammer PATCH /users/{id}/role until something
broke. The limiter is off everywhere else in the suite - it is a
deployment concern, 5/minute on the auth endpoints would make the run
fail randomly - so every test here switches it on, plays the part of
the script that has to be stopped, and checks that the answer is 429.
"""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.core.rate_limit import limiter
from app.core.security import hash_password
from app.main import app
from app.models import User

client = TestClient(app)


def auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def empty_counter():
    """Counters live in memory for the whole run: start every test at zero."""
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture
def users(accounts, db):
    """An admin, and the account it is allowed to rewrite."""
    db.add(
        User(
            name="Limit Admin",
            email="limit-admin@example.com",
            password_hash=hash_password("password123"),
            role="admin",
            email_verified=True,
        )
    )
    db.add(
        User(
            name="Limit Target",
            email="limit-target@example.com",
            password_hash=hash_password("password123"),
            role="customer",
            email_verified=True,
        )
    )
    db.commit()

    target = db.query(User).filter(User.email == "limit-target@example.com").one()

    return SimpleNamespace(
        token=accounts.login(client, "limit-admin@example.com"),
        target_id=target.id,
    )


def assert_blocked_at(statuses, limit):
    """The first `limit` calls go through; the next one is refused."""
    assert 429 not in statuses[:limit], statuses
    assert statuses[limit] == 429, statuses


def test_role_changes_stop_after_five_a_minute(monkeypatch, users):
    monkeypatch.setattr(limiter, "enabled", True)

    statuses = [
        client.patch(
            f"/users/{users.target_id}/role",
            json={"role": "mechanic"},
            headers=auth(users.token),
        ).status_code
        for _ in range(6)
    ]

    assert_blocked_at(statuses, 5)


def test_deleting_users_stops_after_five_a_minute(monkeypatch, users):
    monkeypatch.setattr(limiter, "enabled", True)

    statuses = [
        client.delete(
            f"/users/{users.target_id}", headers=auth(users.token)
        ).status_code
        for _ in range(6)
    ]

    assert_blocked_at(statuses, 5)


def test_editing_a_profile_stops_after_ten_a_minute(monkeypatch, users):
    monkeypatch.setattr(limiter, "enabled", True)

    statuses = [
        client.patch(
            f"/users/{users.target_id}",
            json={"name": "Rewritten"},
            headers=auth(users.token),
        ).status_code
        for _ in range(11)
    ]

    assert_blocked_at(statuses, 10)


def test_replacing_a_profile_stops_after_ten_a_minute(monkeypatch, users):
    monkeypatch.setattr(limiter, "enabled", True)

    payload = {"name": "Replaced", "email": "limit-target@example.com"}

    statuses = [
        client.put(
            f"/users/{users.target_id}",
            json=payload,
            headers=auth(users.token),
        ).status_code
        for _ in range(11)
    ]

    assert_blocked_at(statuses, 10)
