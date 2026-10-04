from pwdlib import PasswordHash
from datetime import datetime, timedelta, timezone

import jwt
import hashlib
import hmac
import secrets


from app.core.config import settings

password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    return password_hash.verify(password, hashed_password)

def create_access_token(data: dict) -> str:
    to_encode = data.copy()

    expire = datetime.now(timezone.utc) + timedelta(minutes=30)
    to_encode["exp"] = expire

    encoded_jwt = jwt.encode(
        to_encode,
        settings.secret_key,
        algorithm=settings.algorithm,
    )

    return encoded_jwt

def verify_token(token: str) -> dict:
    payload = jwt.decode(
        token,
        settings.secret_key,
        algorithms=[settings.algorithm]
    )
    
    return payload

def create_refresh_token() -> str:
    return secrets.token_urlsafe(64)


def hash_refresh_token(token: str) -> str:
    """Deterministic digest that the database can look up by index.

    Refresh tokens carry 64 bytes of randomness, so there is nothing to
    brute force, and the API has to find one row among all of them: a
    salted password hash stores a different value per row, which forces
    a full scan with a password KDF per row. A keyed digest keeps the
    token itself out of storage and lets the unique index do the work.
    """
    return hmac.new(
        settings.secret_key.encode("utf-8"),
        token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()