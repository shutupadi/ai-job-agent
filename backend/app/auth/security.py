"""Password hashing (bcrypt) + JWT access tokens (PyJWT)."""

from __future__ import annotations

import datetime as dt
from typing import Any, Optional

import bcrypt
import jwt

from app.config import settings

# bcrypt hard-limits passwords to 72 bytes; truncate so long inputs don't error.
_BCRYPT_MAX = 72


def hash_password(password: str) -> str:
    pw = password.encode("utf-8")[:_BCRYPT_MAX]
    return bcrypt.hashpw(pw, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: Optional[str]) -> bool:
    if not password_hash:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8")[:_BCRYPT_MAX], password_hash.encode("utf-8"))
    except Exception:
        return False


def create_access_token(user_id: str, extra: Optional[dict] = None) -> str:
    now = dt.datetime.utcnow()
    payload: dict[str, Any] = {
        "sub": user_id,
        "iat": now,
        "exp": now + dt.timedelta(minutes=settings.jwt_expire_minutes),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict:
    """Raises jwt exceptions on invalid/expired tokens."""
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
