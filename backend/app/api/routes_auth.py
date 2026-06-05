"""Auth endpoints — signup / login / me / google."""

from __future__ import annotations

import shutil
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user, is_admin
from app.auth.rate_limit import RateLimiter
from app.auth.security import create_access_token, hash_password, verify_password
from app.config import settings
from app.db import models
from app.db.session import get_db
from app.schemas.schemas import (
    AuthStartResponse,
    ForgotPasswordRequest,
    GoogleAuthRequest,
    LoginRequest,
    PreferencesUpdate,
    ResendOtpRequest,
    ResetPasswordRequest,
    SignupRequest,
    SignupStartRequest,
    TokenResponse,
    UserOut,
    VerifyEmailRequest,
)
from app.services import guest, otp
from app.utils.logger import log

router = APIRouter()

# Throttle credential endpoints to blunt brute-force / signup spam.
_auth_rl = RateLimiter("auth", times=settings.rl_auth_times, seconds=settings.rl_auth_seconds)
# OTP send/verify get their own (slightly tighter) bucket.
_otp_rl = RateLimiter("otp", times=settings.rl_auth_times, seconds=settings.rl_auth_seconds)


def _has_resume(db: Session, user_id: str) -> bool:
    return (
        db.query(models.Resume)
        .filter(models.Resume.user_id == user_id, models.Resume.is_active.is_(True))
        .first()
        is not None
    )


def _user_out(db: Session, user: models.User) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        name=user.name,
        avatar_url=user.avatar_url,
        is_admin=is_admin(user),
        has_resume=_has_resume(db, user.id),
        email_verified=bool(user.email_verified),
        experience_pref=user.experience_pref or "fresher",
    )


def _attach_guest_resume(db: Session, user: models.User, token: str | None) -> None:
    """Move a guest-parsed résumé onto the new account (preserves the upload)."""
    gs = guest.get_active(db, token or "")
    if not gs:
        return
    db.query(models.Resume).filter(
        models.Resume.user_id == user.id, models.Resume.is_active.is_(True)
    ).update({"is_active": False})
    db.add(
        models.Resume(
            user_id=user.id,
            filename=gs.filename,
            raw_text=gs.raw_text,
            parsed_json=gs.parsed_json,
            is_active=True,
        )
    )
    gs.claimed = True


def _start_signup(db: Session, payload: SignupStartRequest):
    """Shared signup logic → returns either a TokenResponse (verification not
    enforced) or an AuthStartResponse (OTP sent, verification pending)."""
    email = payload.email.lower().strip()
    existing = db.query(models.User).filter(models.User.email == email).first()
    if existing and existing.email_verified:
        raise HTTPException(409, "An account with this email already exists.")

    if existing:  # unverified — allow restarting an abandoned signup
        user = existing
        user.password_hash = hash_password(payload.password)
        if payload.name:
            user.name = payload.name.strip() or user.name
    else:
        user = models.User(
            email=email,
            name=(payload.name or "").strip() or None,
            password_hash=hash_password(payload.password),
        )
        db.add(user)
        db.flush()

    _attach_guest_resume(db, user, payload.guest_token)

    if not otp.verification_active():
        otp.mark_verified(user)
        db.commit()
        db.refresh(user)
        return _token_response(db, user)

    code = otp.create_and_send(db, user, "signup")
    db.commit()
    return AuthStartResponse(
        status="otp_sent",
        email=user.email,
        verification_required=True,
        dev_otp=code if otp._expose_dev_otp() else None,
    )


def _token_response(db: Session, user: models.User) -> TokenResponse:
    return TokenResponse(access_token=create_access_token(user.id), user=_user_out(db, user))


@router.post("/signup-start", dependencies=[Depends(_auth_rl)])
def signup_start(payload: SignupStartRequest, db: Session = Depends(get_db)):
    """Begin signup: create the (unverified) account and email a verification
    code. Returns AuthStartResponse (otp_sent) when verification is enforced, or
    a full TokenResponse when it isn't (no email provider in prod / disabled)."""
    return _start_signup(db, payload)


@router.post("/signup", status_code=201, dependencies=[Depends(_auth_rl)])
def signup(payload: SignupRequest, db: Session = Depends(get_db)):
    """Back-compat alias — routed through email verification like signup-start."""
    return _start_signup(
        db,
        SignupStartRequest(email=payload.email, password=payload.password, name=payload.name),
    )


@router.post("/verify-email", response_model=TokenResponse, dependencies=[Depends(_otp_rl)])
def verify_email(payload: VerifyEmailRequest, db: Session = Depends(get_db)):
    """Confirm the emailed code → mark verified → return a logged-in token."""
    email = payload.email.lower().strip()
    user = db.query(models.User).filter(models.User.email == email).first()
    if not user:
        raise HTTPException(400, "Invalid or expired code.")  # generic
    if user.email_verified:
        return _token_response(db, user)  # idempotent
    ok, msg = otp.verify(db, user, payload.code, "signup")
    if not ok:
        db.commit()  # persist the attempt counter
        raise HTTPException(400, msg)
    otp.mark_verified(user)
    db.commit()
    db.refresh(user)
    return _token_response(db, user)


@router.post("/resend-otp", response_model=AuthStartResponse, dependencies=[Depends(_otp_rl)])
def resend_otp(payload: ResendOtpRequest, db: Session = Depends(get_db)):
    """Resend a verification code. Always returns a generic response (no account
    enumeration); throttled per user by a cooldown."""
    email = payload.email.lower().strip()
    user = db.query(models.User).filter(models.User.email == email).first()
    generic = AuthStartResponse(status="otp_sent", email=email, verification_required=True)
    if not user or user.email_verified or not otp.verification_active():
        return generic
    wait = otp.seconds_until_resend(db, user.id, "signup")
    if wait > 0:
        raise HTTPException(429, f"Please wait {wait}s before requesting another code.")
    code = otp.create_and_send(db, user, "signup")
    db.commit()
    generic.dev_otp = code if otp._expose_dev_otp() else None
    return generic


@router.post("/forgot-password", response_model=AuthStartResponse, dependencies=[Depends(_otp_rl)])
def forgot_password(payload: ForgotPasswordRequest, db: Session = Depends(get_db)):
    """Email a password-reset code. Always returns a generic response (no account
    enumeration); throttled per user."""
    email = payload.email.lower().strip()
    user = db.query(models.User).filter(models.User.email == email).first()
    out = AuthStartResponse(status="otp_sent", email=email, verification_required=True)
    if not user:
        log.info(f"[forgot-password] no account for {email} — generic response")
        return out
    # NOTE: we intentionally send for Google-only accounts too (no password yet),
    # so the owner can SET a password via the reset flow and use email login.
    if otp.seconds_until_resend(db, user.id, "password_reset") > 0:
        log.info(f"[forgot-password] cooldown active for {email} — skipping resend")
        return out  # silently respect cooldown (still generic)
    code = otp.create_and_send(db, user, "password_reset")
    db.commit()
    log.info(
        f"[forgot-password] reset code issued for {email} "
        f"(provider={settings.email_provider or 'none'}, email_enabled={otp.alerts.email_enabled()})"
    )
    out.dev_otp = code if otp._expose_dev_otp() else None
    return out


@router.post("/reset-password", response_model=TokenResponse, dependencies=[Depends(_otp_rl)])
def reset_password(payload: ResetPasswordRequest, db: Session = Depends(get_db)):
    """Verify the reset code and set a new password (then log in)."""
    email = payload.email.lower().strip()
    user = db.query(models.User).filter(models.User.email == email).first()
    if not user:
        raise HTTPException(400, "Invalid or expired code.")  # generic
    ok, msg = otp.verify(db, user, payload.code, "password_reset")
    if not ok:
        db.commit()
        raise HTTPException(400, msg)
    user.password_hash = hash_password(payload.new_password)
    # Completing a reset proves control of the inbox → treat as verified.
    if not user.email_verified:
        otp.mark_verified(user)
    db.commit()
    db.refresh(user)
    return _token_response(db, user)


@router.post("/login", response_model=TokenResponse, dependencies=[Depends(_auth_rl)])
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    email = payload.email.lower().strip()
    user = db.query(models.User).filter(models.User.email == email).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "Invalid email or password.")
    if not user.is_active:
        raise HTTPException(403, "Account disabled.")
    if otp.verification_active() and not user.email_verified:
        # Help them along: (re)send a code if the cooldown has elapsed.
        if otp.seconds_until_resend(db, user.id, "signup") == 0:
            otp.create_and_send(db, user, "signup")
            db.commit()
        raise HTTPException(403, "Email not verified. We've emailed you a code.")
    return _token_response(db, user)


@router.get("/me", response_model=UserOut)
def me(user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _user_out(db, user)


@router.patch("/me", response_model=UserOut)
def update_me(
    payload: PreferencesUpdate,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update the current user's preferences (e.g. fresher mode). Switching to
    fresher immediately removes already-ranked senior jobs from the shortlist
    (tailored/applied ones are kept)."""
    user.experience_pref = payload.experience_pref
    if payload.experience_pref == "fresher":
        from app.services.experience_filter import is_fresher_friendly

        pairs = (
            db.query(models.Ranking, models.Job)
            .join(models.Job, models.Job.id == models.Ranking.job_id)
            .filter(models.Ranking.user_id == user.id, models.Ranking.status == "ranked")
            .all()
        )
        to_del = [
            rk.id
            for rk, job in pairs
            if not is_fresher_friendly(job.title or "", job.description or "")
        ]
        if to_del:
            db.query(models.Ranking).filter(models.Ranking.id.in_(to_del)).delete(
                synchronize_session=False
            )
    db.commit()
    db.refresh(user)
    return _user_out(db, user)


@router.delete("/me", status_code=204)
def delete_me(
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Permanently delete the current user and ALL their data (résumés, rankings,
    applications, tailored docs cascade via FK ondelete). Also removes uploaded
    files from disk. This is irreversible."""
    uid = user.id
    # Best-effort: wipe the user's uploaded-file directory.
    try:
        updir = Path(settings.storage_dir) / "uploads" / uid
        if updir.exists():
            shutil.rmtree(updir, ignore_errors=True)
    except Exception:
        pass
    # Explicitly remove dependent rows so deletion is correct on every backend
    # (Postgres has ON DELETE CASCADE; SQLite does not enforce FKs by default).
    for model in (
        models.Application,
        models.Ranking,
        models.ResumeVersion,
        models.CoverLetter,
        models.Resume,
    ):
        db.query(model).filter(model.user_id == uid).delete(synchronize_session=False)
    db.delete(user)
    db.commit()
    return None


@router.post("/google", response_model=TokenResponse, dependencies=[Depends(_auth_rl)])
def google(payload: GoogleAuthRequest, db: Session = Depends(get_db)):
    """Sign in with a Google ID token (verified via Google's tokeninfo)."""
    if not settings.google_client_id:
        raise HTTPException(400, "Google sign-in is not configured on the server.")
    try:
        r = httpx.get(
            "https://oauth2.googleapis.com/tokeninfo",
            params={"id_token": payload.credential},
            timeout=15,
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Could not reach Google: {e}")
    if r.status_code != 200:
        raise HTTPException(401, "Invalid Google token.")
    info = r.json()
    if info.get("aud") != settings.google_client_id:
        raise HTTPException(401, "Google token audience mismatch.")
    email = (info.get("email") or "").lower().strip()
    sub = info.get("sub")
    if not email or not sub:
        raise HTTPException(401, "Google token missing email/sub.")

    user = db.query(models.User).filter(models.User.google_sub == sub).first()
    if not user:
        user = db.query(models.User).filter(models.User.email == email).first()
        if user:
            user.google_sub = sub
            if not user.avatar_url:
                user.avatar_url = info.get("picture")
        else:
            user = models.User(
                email=email,
                name=info.get("name"),
                google_sub=sub,
                avatar_url=info.get("picture"),
            )
            db.add(user)
    # Google has already verified this email address.
    if not user.email_verified:
        otp.mark_verified(user)
    db.commit()
    db.refresh(user)
    return _token_response(db, user)
