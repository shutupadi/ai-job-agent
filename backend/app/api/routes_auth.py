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
    GoogleAuthRequest,
    LoginRequest,
    PreferencesUpdate,
    SignupRequest,
    TokenResponse,
    UserOut,
)

router = APIRouter()

# Throttle credential endpoints to blunt brute-force / signup spam.
_auth_rl = RateLimiter("auth", times=settings.rl_auth_times, seconds=settings.rl_auth_seconds)


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
        experience_pref=user.experience_pref or "fresher",
    )


def _token_response(db: Session, user: models.User) -> TokenResponse:
    return TokenResponse(access_token=create_access_token(user.id), user=_user_out(db, user))


@router.post(
    "/signup",
    response_model=TokenResponse,
    status_code=201,
    dependencies=[Depends(_auth_rl)],
)
def signup(payload: SignupRequest, db: Session = Depends(get_db)):
    email = payload.email.lower().strip()
    if db.query(models.User).filter(models.User.email == email).first():
        raise HTTPException(409, "An account with this email already exists.")
    user = models.User(
        email=email,
        name=(payload.name or "").strip() or None,
        password_hash=hash_password(payload.password),
    )
    db.add(user)
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
    db.commit()
    db.refresh(user)
    return _token_response(db, user)
