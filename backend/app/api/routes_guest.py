"""
Guest (no-account) résumé upload + preview.

A visitor uploads a résumé, we parse it with the SAME parser used for members,
store it briefly against an unguessable token, and return a career-profile
preview plus a free deterministic "sample matches" teaser. They then sign up to
save it and unlock full ranking. No LLM cost is spent here.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.routes_resume import _validate_upload
from app.auth.rate_limit import RateLimiter
from app.config import settings
from app.db import models
from app.db.session import get_db
from app.schemas.schemas import CareerProfileOut, GuestJobSample, GuestUploadResponse
from app.services import guest, resume_parser

router = APIRouter()

_guest_rl = RateLimiter(
    "guest_upload", times=settings.rl_upload_times, seconds=settings.rl_upload_seconds
)


def _profile_out(parsed: dict) -> CareerProfileOut:
    return CareerProfileOut(
        name=parsed.get("name") or "",
        experience_years=int(parsed.get("experience_years") or 0),
        seniority=parsed.get("seniority") or "",
        role_direction=parsed.get("role_direction") or "",
        current_role=parsed.get("current_role") or "",
        current_company=parsed.get("current_company") or "",
        target_titles=parsed.get("target_titles") or [],
        target_job_types=parsed.get("target_job_types") or [],
        domains=parsed.get("domains") or [],
        primary_skills=parsed.get("primary_skills") or [],
        summary=parsed.get("summary") or "",
    )


@router.post("/upload", response_model=GuestUploadResponse, dependencies=[Depends(_guest_rl)])
async def guest_upload(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Parse a résumé for a not-yet-registered visitor and return a preview."""
    data = await file.read()
    _validate_upload(file.filename or "", data)
    try:
        text, parsed = resume_parser.extract_and_parse(file.filename or "", data)
    except ValueError as e:
        raise HTTPException(422, str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"Could not parse résumé: {e}")

    guest.cleanup_expired(db)  # opportunistic housekeeping
    gs = guest.create_session(db, file.filename, text, parsed)
    samples = guest.sample_matches(db, parsed)
    db.commit()
    return GuestUploadResponse(
        token=gs.token,
        profile=_profile_out(parsed),
        sample_matches=[GuestJobSample(**s) for s in samples],
    )


@router.get("/{token}", response_model=GuestUploadResponse)
def get_guest(token: str, db: Session = Depends(get_db)):
    """Re-fetch a guest preview (e.g. after a page reload before signup)."""
    gs = guest.get_active(db, token)
    if not gs:
        raise HTTPException(404, "Guest session not found or expired.")
    return GuestUploadResponse(
        token=gs.token,
        profile=_profile_out(gs.parsed_json or {}),
        sample_matches=guest.sample_matches(db, gs.parsed_json or {}),
    )
