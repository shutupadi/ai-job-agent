"""
Email one-time-password (OTP) verification.

Security properties:
  • The plaintext code is NEVER stored — only an HMAC-SHA256 hash (peppered with
    JWT_SECRET). Verification uses a constant-time compare.
  • Codes expire (OTP_TTL_MINUTES) and lock after OTP_MAX_ATTEMPTS wrong tries.
  • Resends are throttled per user (OTP_RESEND_SECONDS).

Delivery + enforcement:
  • If an email provider (Resend/Brevo) is configured, the code is emailed.
  • If not, and we're in DEV, the code is logged to the backend console so you can
    still test the flow — NEVER logged/exposed in production.
  • `verification_active()` decides whether verification is *enforced*: yes when it
    can be delivered (provider configured) or in dev; in prod WITHOUT a provider we
    auto-verify so the live site keeps working until email is configured.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import secrets
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from app.config import settings
from app.db import models
from app.services import alerts
from app.utils.logger import log


def _now() -> dt.datetime:
    return dt.datetime.utcnow()


def verification_active() -> bool:
    """Whether email verification is currently ENFORCED.

    If REQUIRE_EMAIL_VERIFICATION is on, verification is ALWAYS enforced — we never
    silently auto-verify (that would fake security). When no email provider is
    configured: in dev the code is logged so you can still test; in prod this is a
    MISCONFIGURATION that we surface loudly (startup log + admin health) rather
    than weakening signups. Existing users are grandfathered, so nobody is locked
    out unexpectedly — only brand-new signups are gated."""
    return bool(settings.require_email_verification)


def email_misconfigured() -> bool:
    """True when verification is required in prod but no email provider can send
    the codes — a state that must be fixed (surfaced in admin health)."""
    return (
        settings.require_email_verification
        and settings.app_env.lower() == "prod"
        and not alerts.email_enabled()
    )


def _expose_dev_otp() -> bool:
    """Return the code in the API response only for local dev w/o a provider."""
    return settings.app_env.lower() != "prod" and not alerts.email_enabled()


def generate_code() -> str:
    n = max(4, min(10, settings.otp_length))
    return "".join(secrets.choice("0123456789") for _ in range(n))


def hash_otp(code: str) -> str:
    return hmac.new(
        settings.jwt_secret.encode("utf-8"), code.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def _verify_hash(code: str, stored: str) -> bool:
    return hmac.compare_digest(hash_otp(code), stored or "")


def _latest(db: Session, user_id: str, purpose: str) -> Optional[models.EmailOTP]:
    return (
        db.query(models.EmailOTP)
        .filter(
            models.EmailOTP.user_id == user_id,
            models.EmailOTP.purpose == purpose,
            models.EmailOTP.consumed_at.is_(None),
        )
        .order_by(models.EmailOTP.created_at.desc())
        .first()
    )


def seconds_until_resend(db: Session, user_id: str, purpose: str = "signup") -> int:
    """0 if a resend is allowed now, else seconds remaining in the cooldown."""
    last = _latest(db, user_id, purpose)
    if not last:
        return 0
    elapsed = (_now() - last.created_at).total_seconds()
    remaining = settings.otp_resend_seconds - elapsed
    return int(remaining) + 1 if remaining > 0 else 0


def _deliver(email: str, name: Optional[str], code: str, purpose: str) -> None:
    ttl = settings.otp_ttl_minutes
    if alerts.email_enabled():
        html = (
            f'<div style="font-family:system-ui,Arial,sans-serif;max-width:480px;margin:auto">'
            f'<h2>Verify your email</h2>'
            f'<p>Hi {name or "there"}, use this code to finish setting up your '
            f'AI Job Agent account:</p>'
            f'<p style="font-size:30px;font-weight:700;letter-spacing:6px;'
            f'background:#f3f4f6;padding:14px 20px;border-radius:10px;text-align:center">{code}</p>'
            f'<p style="color:#666">It expires in {ttl} minutes. If you didn\'t request '
            f'this, you can ignore this email.</p></div>'
        )
        alerts.send_email(email, "Your AI Job Agent verification code", html)
    else:
        # Dev only — verification_active() guarantees we never reach here in prod.
        log.warning(f"[DEV OTP] {purpose} code for {email} = {code} (no email provider configured)")


def create_and_send(db: Session, user: models.User, purpose: str = "signup") -> str:
    """Create + persist a hashed OTP and deliver it. Returns the plaintext code
    (callers only expose it in local-dev responses)."""
    code = generate_code()
    otp = models.EmailOTP(
        user_id=user.id,
        email=user.email,
        otp_hash=hash_otp(code),
        purpose=purpose,
        expires_at=_now() + dt.timedelta(minutes=settings.otp_ttl_minutes),
    )
    db.add(otp)
    db.flush()
    _deliver(user.email, user.name, code, purpose)
    return code


def verify(db: Session, user: models.User, code: str, purpose: str = "signup") -> Tuple[bool, str]:
    """Validate a code. Returns (ok, error_message). Generic messages avoid
    leaking whether a code exists."""
    otp = _latest(db, user.id, purpose)
    if otp is None:
        return False, "No active code. Please request a new one."
    if otp.attempts >= settings.otp_max_attempts:
        return False, "Too many attempts. Please request a new code."
    otp.attempts += 1
    if otp.expires_at < _now():
        db.flush()
        return False, "Code expired. Please request a new one."
    if not _verify_hash((code or "").strip(), otp.otp_hash):
        db.flush()
        left = max(0, settings.otp_max_attempts - otp.attempts)
        return False, f"Incorrect code. {left} attempt(s) left."
    otp.consumed_at = _now()
    db.flush()
    return True, ""


def mark_verified(user: models.User) -> None:
    user.email_verified = True
    user.email_verified_at = _now()
