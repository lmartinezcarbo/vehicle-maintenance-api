import secrets

from pwdlib import PasswordHash
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from app.models.one_time_code import OneTimeCode

password_hash = PasswordHash.recommended()


def generate_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_code(code: str) -> str:
    return password_hash.hash(code)

def create_one_time_code(
    db: Session,
    user_id: int,
    purpose: str,
) -> str:
    now = datetime.now(timezone.utc)

    active_codes = (
        db.query(OneTimeCode)
        .filter(
            OneTimeCode.user_id == user_id,
            OneTimeCode.purpose == purpose,
            OneTimeCode.used_at.is_(None),
            OneTimeCode.revoked_at.is_(None),
            OneTimeCode.expires_at > now,
        )
        .all()
    )

    for existing_code in active_codes:
        existing_code.revoked_at = now

    code = generate_code()

    one_time_code = OneTimeCode(
        user_id=user_id,
        code_hash=hash_code(code),
        purpose=purpose,
        expires_at=now + timedelta(minutes=10),
        attempts=0,
        max_attempts=5,
    )

    db.add(one_time_code)
    db.commit()
    db.refresh(one_time_code)

    return code

def verify_one_time_code(
    db: Session,
    user_id: int,
    purpose: str,
    code: str,
) -> bool:
    now = datetime.now(timezone.utc)

    one_time_code = (
        db.query(OneTimeCode)
        .filter(
            OneTimeCode.user_id == user_id,
            OneTimeCode.purpose == purpose,
            OneTimeCode.used_at.is_(None),
            OneTimeCode.revoked_at.is_(None),
        )
        .order_by(OneTimeCode.id.desc())
        .first()
    )

    if one_time_code is None:
        return False

    if one_time_code.expires_at <= now:
        return False

    if one_time_code.attempts >= one_time_code.max_attempts:
        return False

    one_time_code.attempts += 1

    if not password_hash.verify(code, one_time_code.code_hash):
        db.commit()
        return False

    one_time_code.used_at = now

    db.commit()

    return True