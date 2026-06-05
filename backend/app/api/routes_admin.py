"""Admin endpoints — read-only platform visibility (users, résumés, runs, stats).

Access is gated by `get_current_admin` (User.is_admin row flag OR membership in
the ADMIN_EMAILS env list). These endpoints never mutate data — they exist so an
operator can verify per-user isolation, parser quality, and pipeline health from
the UI instead of shelling into the DB.
"""

from __future__ import annotations

import os
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth.deps import get_current_admin, is_admin
from app.config import settings
from app.db import models
from app.db.session import get_db
from app.schemas.schemas import (
    AdminResumeOut,
    AdminSourceOut,
    AdminStats,
    AdminUserOut,
    CompanyTierOut,
    CompanyTierUpsert,
    RunOut,
    SourceHealthOut,
    SystemHealthOut,
)
from app.services import alerts, company_quality, otp, source_health, sources_meta

router = APIRouter()


def _login_method(u: models.User) -> str:
    if u.google_sub and u.password_hash:
        return "google+password"
    if u.google_sub:
        return "google"
    if u.password_hash:
        return "password"
    return "-"


def _resume_out(r: models.Resume) -> AdminResumeOut:
    pj = r.parsed_json or {}
    skills = pj.get("skills")
    if isinstance(skills, dict):
        n_skills = sum(len(v or []) for v in skills.values() if isinstance(v, list))
    elif isinstance(skills, list):
        n_skills = len(skills)
    else:
        n_skills = 0
    yrs = pj.get("experience_years")
    return AdminResumeOut(
        id=r.id,
        filename=r.filename,
        is_active=r.is_active,
        experience_years=int(yrs) if isinstance(yrs, (int, float)) else None,
        seniority=pj.get("seniority") or None,
        role_direction=pj.get("role_direction") or None,
        n_skills=n_skills,
        text_chars=len(r.raw_text or ""),
        on_disk=bool(r.pdf_path and os.path.exists(r.pdf_path)),
        created_at=r.created_at,
    )


@router.get("/stats", response_model=AdminStats)
def stats(db: Session = Depends(get_db), _: models.User = Depends(get_current_admin)):
    users = db.query(models.User).all()
    with_resume = (
        db.query(models.Resume.user_id)
        .filter(models.Resume.is_active.is_(True))
        .distinct()
        .count()
    )
    last_run = db.query(models.Run).order_by(models.Run.started_at.desc()).first()
    return AdminStats(
        total_users=len(users),
        active_users=sum(1 for u in users if u.is_active),
        users_with_resume=with_resume,
        total_jobs=db.query(models.Job).count(),
        total_rankings=db.query(models.Ranking).count(),
        total_applications=db.query(models.Application).count(),
        last_run=RunOut.model_validate(last_run) if last_run else None,
    )


@router.get("/users", response_model=List[AdminUserOut])
def list_users(
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_admin),
    limit: int = Query(200, le=1000),
    offset: int = 0,
):
    users = (
        db.query(models.User)
        .order_by(models.User.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    out: List[AdminUserOut] = []
    threshold = settings.min_rank_to_apply
    for u in users:
        resumes = (
            db.query(models.Resume)
            .filter(models.Resume.user_id == u.id)
            .order_by(models.Resume.created_at.desc())
            .all()
        )
        n_ranked = db.query(models.Ranking).filter(models.Ranking.user_id == u.id).count()
        n_short = (
            db.query(models.Ranking)
            .filter(
                models.Ranking.user_id == u.id,
                models.Ranking.rank_score >= threshold,
            )
            .count()
        )
        n_app = (
            db.query(models.Application)
            .filter(models.Application.user_id == u.id)
            .count()
        )
        out.append(
            AdminUserOut(
                id=u.id,
                email=u.email,
                name=u.name,
                is_admin=is_admin(u),
                is_active=u.is_active,
                experience_pref=u.experience_pref or "fresher",
                login_method=_login_method(u),
                created_at=u.created_at,
                n_resumes=len(resumes),
                n_ranked=n_ranked,
                n_shortlisted=n_short,
                n_applied=n_app,
                resumes=[_resume_out(r) for r in resumes],
            )
        )
    return out


@router.get("/runs", response_model=List[RunOut])
def list_runs(
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_admin),
    limit: int = Query(30, le=200),
):
    rows = (
        db.query(models.Run)
        .order_by(models.Run.started_at.desc())
        .limit(limit)
        .all()
    )
    return [RunOut.model_validate(r) for r in rows]


@router.get("/source-health", response_model=List[SourceHealthOut])
def source_health_report(
    db: Session = Depends(get_db), _: models.User = Depends(get_current_admin)
):
    return [SourceHealthOut.model_validate(r) for r in source_health.all_health(db)]


@router.get("/sources", response_model=List[AdminSourceOut])
def sources_report(
    db: Session = Depends(get_db), _: models.User = Depends(get_current_admin)
):
    """Rich per-source view: enabled, real-vs-stub, missing credentials, confidence,
    and the latest run health — everything an operator needs at a glance."""
    health = {h.source: h for h in source_health.all_health(db)}
    out: List[AdminSourceOut] = []
    for name, meta in sources_meta.META.items():
        h = health.get(name)
        missing = sources_meta.missing_credentials(name)
        out.append(
            AdminSourceOut(
                name=name,
                enabled=bool(getattr(settings, f"enable_{name}", False)),
                stub=bool(meta.get("stub")),
                kind=meta.get("kind", "unknown"),
                confidence=meta.get("confidence", "unknown"),
                configured=len(missing) == 0,
                missing_credentials=missing,
                last_run_at=h.last_run_at if h else None,
                last_success_at=h.last_success_at if h else None,
                jobs_found=h.jobs_found if h else 0,
                jobs_added=h.jobs_added if h else 0,
                failures=h.failures if h else 0,
                last_error=h.last_error if h else None,
            )
        )
    # enabled first, then by name
    out.sort(key=lambda s: (not s.enabled, s.name))
    return out


@router.get("/system-health", response_model=SystemHealthOut)
def system_health(_: models.User = Depends(get_current_admin)):
    """Email/verification configuration status — flags the prod misconfig where
    verification is required but no provider can deliver codes."""
    return SystemHealthOut(
        app_env=settings.app_env,
        email_provider=settings.email_provider or "",
        email_from=settings.email_from or "",
        email_enabled=alerts.email_enabled(),
        sender_freemail=alerts.sender_is_freemail(),
        verification_required=settings.require_email_verification,
        verification_active=otp.verification_active(),
        email_misconfigured=otp.email_misconfigured(),
    )


@router.get("/email-test")
def email_test(
    to: Optional[str] = None,
    admin: models.User = Depends(get_current_admin),
):
    """Send a real test email and return exactly what the provider said. Use this
    to debug OTP delivery (blocked IP, unverified sender, bad key, etc.).
    Defaults to emailing the admin's own address."""
    from app.services import otp

    result = alerts.send_test(to or admin.email)
    result["verification_active"] = otp.verification_active()
    return result


@router.get("/company-tiers", response_model=List[CompanyTierOut])
def list_company_tiers(
    db: Session = Depends(get_db), _: models.User = Depends(get_current_admin)
):
    rows = db.query(models.CompanyTierOverride).order_by(models.CompanyTierOverride.tier).all()
    return [CompanyTierOut(company=r.company, tier=r.tier) for r in rows]


@router.put("/company-tiers", response_model=CompanyTierOut)
def upsert_company_tier(
    payload: CompanyTierUpsert,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_admin),
):
    norm = company_quality.normalize(payload.company)
    row = db.get(models.CompanyTierOverride, norm)
    if row is None:
        row = models.CompanyTierOverride(company_norm=norm, company=payload.company.strip(), tier=payload.tier)
        db.add(row)
    else:
        row.company = payload.company.strip()
        row.tier = payload.tier
    db.commit()
    return CompanyTierOut(company=row.company, tier=row.tier)
