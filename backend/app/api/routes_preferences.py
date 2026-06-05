"""
User preferences + editable career profile.

Preferences (target roles, salary, cities, work mode, must/nice skills, blocked
industries, excluded keywords, alert settings) feed directly into ranking.

The career profile is the structured, USER-EDITABLE view of the parsed résumé
(AI parsing is never perfect) — edits are written back onto the active résumé's
parsed_json so the next rank uses the corrected values.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user, get_verified_user
from app.db import models
from app.db.session import get_db
from app.schemas.schemas import (
    CareerProfileOut,
    CareerProfileUpdate,
    UserPreferencesOut,
    UserPreferencesUpdate,
)

router = APIRouter()

_PROFILE_FIELDS = (
    "experience_years", "seniority", "role_direction", "current_role",
    "current_company", "target_titles", "target_job_types", "domains",
    "primary_skills", "summary",
)


def _get_or_create_prefs(db: Session, user_id: str) -> models.UserPreferences:
    p = db.get(models.UserPreferences, user_id)
    if p is None:
        p = models.UserPreferences(user_id=user_id)
        db.add(p)
        db.flush()
    return p


def _prefs_out(p: models.UserPreferences) -> UserPreferencesOut:
    return UserPreferencesOut(
        target_roles=p.target_roles or [],
        experience_level=p.experience_level,
        min_salary_lpa=p.min_salary_lpa,
        preferred_cities=p.preferred_cities or [],
        work_modes=p.work_modes or [],
        job_types=p.job_types or [],
        prioritized_industries=p.prioritized_industries or [],
        blocked_industries=p.blocked_industries or [],
        preferred_countries=p.preferred_countries or [],
        needs_sponsorship=bool(p.needs_sponsorship),
        excluded_keywords=p.excluded_keywords or [],
        must_have_skills=p.must_have_skills or [],
        nice_to_have_skills=p.nice_to_have_skills or [],
        alert_instant=bool(p.alert_instant),
        alert_daily_digest=bool(p.alert_daily_digest),
    )


@router.get("", response_model=UserPreferencesOut)
def get_preferences(
    db: Session = Depends(get_db), user: models.User = Depends(get_current_user)
):
    p = db.get(models.UserPreferences, user.id)
    return _prefs_out(p) if p else UserPreferencesOut()


@router.put("", response_model=UserPreferencesOut)
def update_preferences(
    payload: UserPreferencesUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_verified_user),
):
    p = _get_or_create_prefs(db, user.id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(p, field, value)
    db.commit()
    db.refresh(p)
    return _prefs_out(p)


@router.get("/profile", response_model=CareerProfileOut)
def get_profile(
    db: Session = Depends(get_db), user: models.User = Depends(get_current_user)
):
    row = (
        db.query(models.Resume)
        .filter(models.Resume.user_id == user.id, models.Resume.is_active.is_(True))
        .order_by(models.Resume.created_at.desc())
        .first()
    )
    if not row:
        raise HTTPException(404, "Upload your résumé first.")
    pj = row.parsed_json or {}
    return CareerProfileOut(
        name=pj.get("name") or "",
        experience_years=int(pj.get("experience_years") or 0),
        seniority=pj.get("seniority") or "",
        role_direction=pj.get("role_direction") or "",
        current_role=pj.get("current_role") or "",
        current_company=pj.get("current_company") or "",
        target_titles=pj.get("target_titles") or [],
        target_job_types=pj.get("target_job_types") or [],
        domains=pj.get("domains") or [],
        primary_skills=pj.get("primary_skills") or [],
        summary=pj.get("summary") or "",
    )


@router.put("/profile", response_model=CareerProfileOut)
def update_profile(
    payload: CareerProfileUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Patch the active résumé's structured profile (used by ranking)."""
    row = (
        db.query(models.Resume)
        .filter(models.Resume.user_id == user.id, models.Resume.is_active.is_(True))
        .order_by(models.Resume.created_at.desc())
        .first()
    )
    if not row:
        raise HTTPException(404, "Upload your résumé first.")
    pj = dict(row.parsed_json or {})
    for field, value in payload.model_dump(exclude_unset=True).items():
        if field in _PROFILE_FIELDS and value is not None:
            pj[field] = value
    row.parsed_json = pj
    # SQLAlchemy needs an explicit flag for in-place JSON mutation on some backends.
    from sqlalchemy.orm.attributes import flag_modified

    flag_modified(row, "parsed_json")
    db.commit()
    return get_profile(db, user)
