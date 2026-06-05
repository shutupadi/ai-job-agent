"""FastAPI auth dependencies — resolve the current user from a Bearer token."""

from __future__ import annotations

from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth.security import decode_token
from app.config import settings
from app.db import models
from app.db.session import get_db

_bearer = HTTPBearer(auto_error=False)


def is_admin(user: "models.User") -> bool:
    """Admin if flagged on the row OR listed in ADMIN_EMAILS (request-time)."""
    return bool(getattr(user, "is_admin", False)) or settings.is_admin_email(user.email)


def get_current_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    db: Session = Depends(get_db),
) -> models.User:
    """Require a valid token; raise 401 otherwise."""
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    try:
        payload = decode_token(creds.credentials)
        user_id = payload.get("sub")
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    user = db.get(models.User, user_id) if user_id else None
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found or inactive")
    return user


def get_current_admin(
    user: models.User = Depends(get_current_user),
) -> models.User:
    """Require an admin (row flag or ADMIN_EMAILS membership); 403 otherwise."""
    if not is_admin(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin access required")
    return user


def get_verified_user(
    user: models.User = Depends(get_current_user),
) -> models.User:
    """Require a logged-in AND email-verified user for sensitive actions
    (run pipeline, rerank, save/feedback, tailor, mark applied, set alerts).

    When verification isn't being enforced (no email provider in prod, or it's
    disabled), this is equivalent to get_current_user — so the platform degrades
    gracefully and never locks people out."""
    # Imported here to avoid a circular import (services → config → …).
    from app.services.otp import verification_active

    if verification_active() and not user.email_verified:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Please verify your email to use this feature.",
        )
    return user


def get_current_user_optional(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    db: Session = Depends(get_db),
) -> Optional[models.User]:
    """Like get_current_user but returns None instead of raising (public routes)."""
    if creds is None:
        return None
    try:
        payload = decode_token(creds.credentials)
        return db.get(models.User, payload.get("sub"))
    except Exception:
        return None
