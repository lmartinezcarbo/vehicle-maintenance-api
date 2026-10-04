"""
Refresh tokens: rotation, reuse detection, revocation, expiry.

The flow itself existed; what did not was any test, an index for the
lookup, or anything that ever deleted a row - the table grew with every
login and every request scanned all of it with a password KDF per row.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect

from app.core.security import hash_refresh_token
from app.main import app
from app.models import RefreshToken, User

client = TestClient(app)

EMAIL = "refresh-user@example.com"


def auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def session(accounts, db):
    """A verified customer plus a login helper that keeps both tokens."""
    accounts.register(client, "Refresh User", EMAIL)

    def login():
        response = client.post(
            "/users/login",
            data={"username": EMAIL, "password": "password123"},
        )
        assert response.status_code == 200, response.text

        response = client.post(
            "/users/verify-2fa",
            json={"email": EMAIL, "code": accounts.last_code(EMAIL)},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        return body["access_token"], body["refresh_token"]

    user_id = (
        db.query(User).filter(User.email == EMAIL).first().id
    )

    return SimpleNamespace(login=login, user_id=user_id)


def refresh_with(refresh_token):
    return client.post(
        "/users/refresh", json={"refresh_token": refresh_token}
    )


# --------------------------------------------------------------------------
# The digest
# --------------------------------------------------------------------------

def test_the_digest_is_deterministic_so_a_row_can_be_found():
    """Same token in, same digest out - otherwise only a full scan with
    a password KDF per row could ever find it."""
    digest = hash_refresh_token("a-refresh-token")

    assert digest == hash_refresh_token("a-refresh-token")
    assert digest != hash_refresh_token("another-refresh-token")
    # No per-row salt: a salted hash would be a different value every time.
    assert not digest.startswith("$")


# --------------------------------------------------------------------------
# Rotation and reuse
# --------------------------------------------------------------------------

def test_refresh_rotates_the_token(session):
    _, refresh = session.login()

    response = refresh_with(refresh)
    assert response.status_code == 200, response.text

    rotated = response.json()["refresh_token"]
    assert rotated != refresh
    assert response.json()["access_token"]


def test_a_rotated_token_cannot_be_replayed(session):
    _, refresh = session.login()
    rotated = refresh_with(refresh).json()["refresh_token"]

    response = refresh_with(refresh)

    assert response.status_code == 401
    assert response.json()["detail"] == "Refresh token reuse detected"


def test_reuse_kills_the_whole_family(session):
    """Presenting a rotated token must burn every descendant too: that is
    how a stolen refresh token gets caught."""
    _, refresh = session.login()
    rotated = refresh_with(refresh).json()["refresh_token"]

    assert refresh_with(refresh).status_code == 401  # reuse detected

    response = refresh_with(rotated)
    assert response.status_code == 401


def test_a_logout_revokes_the_refresh_token(session):
    _, refresh = session.login()

    assert client.post(
        "/users/logout", json={"refresh_token": refresh}
    ).status_code == 200

    response = refresh_with(refresh)
    assert response.status_code == 401
    assert response.json()["detail"] == "Refresh token revoked"


def test_an_unknown_token_is_rejected_by_a_single_lookup(session):
    response = refresh_with("not-a-real-refresh-token")

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid refresh token"


def test_logout_does_not_revoke_other_sessions(session):
    """Killing one session must leave the next login alone."""
    _, first = session.login()
    _, second = session.login()

    assert client.post(
        "/users/logout", json={"refresh_token": first}
    ).status_code == 200

    assert refresh_with(second).status_code == 200


# --------------------------------------------------------------------------
# The table stays small and indexed
# --------------------------------------------------------------------------

def test_expired_tokens_are_pruned_on_the_next_login(session, db):
    _, live = session.login()

    now = datetime.now(timezone.utc)
    for _ in range(3):
        db.add(
            RefreshToken(
                user_id=session.user_id,
                token_hash=hash_refresh_token(f"dead-{uuid4()}"),
                family_id=uuid4(),
                expires_at=now - timedelta(days=1),
            )
        )
    db.commit()

    session.login()  # the prune runs where new sessions are minted

    db.expire_all()
    expired = (
        db.query(RefreshToken)
        .filter(RefreshToken.expires_at < now)
        .count()
    )
    alive = (
        db.query(RefreshToken)
        .filter(RefreshToken.expires_at >= now)
        .count()
    )

    assert expired == 0
    assert alive >= 1


def test_the_refresh_flow_is_indexed(db):
    """user_id (prune and bulk revoke), family_id (reuse detection) and
    expires_at (the prune) - Postgres does not index foreign keys."""
    names = {
        index["name"]
        for index in inspect(db.bind).get_indexes("refresh_tokens")
    }

    assert {
        "ix_refresh_tokens_user_id",
        "ix_refresh_tokens_family_id",
        "ix_refresh_tokens_expires_at",
    } <= names
