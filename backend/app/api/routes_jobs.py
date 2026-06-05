"""Job endpoints (per-user) — ranked list / get / mark-applied."""

from __future__ import annotations

import datetime as dt
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user, get_verified_user
from app.auth.rate_limit import RateLimiter
from app.config import settings
from app.db import models
from app.db.session import get_db
from app.schemas.schemas import (
    FeedbackRequest,
    JobListOut,
    JobOut,
    MarkAppliedRequest,
    RerankResponse,
)
from app.services import company_quality, sources_meta, user_context
from app.services.pipeline import run_pipeline
from app.utils.logger import log

router = APIRouter()

# Rankings we never silently discard on a reset — they represent work the user
# already invested (a tailored résumé / a recorded application).
_PROTECTED_STATUSES = ("tailored", "applied")

_run_rl = RateLimiter("run", times=settings.rl_run_times, seconds=settings.rl_run_seconds)


def _job_out(
    job: models.Job,
    rk: Optional[models.Ranking],
    tier: Optional[int] = None,
    watchlisted: bool = False,
) -> JobOut:
    """Merge a shared Job with THIS user's Ranking into the API shape."""
    if tier is None:
        tier = company_quality.tier_for(job.company)
    sig = (rk.match_signals if rk else None) or {}
    return JobOut(
        id=job.id,
        source=job.source,
        external_id=job.external_id,
        url=job.url,
        title=job.title,
        company=job.company,
        location=job.location,
        remote=job.remote,
        department=job.department,
        description=job.description,
        salary_text=job.salary_text,
        posted_at=job.posted_at,
        discovered_at=job.discovered_at,
        rank_score=rk.rank_score if rk else None,
        rank_breakdown=rk.rank_breakdown if rk else None,
        rank_reasoning=rk.rank_reasoning if rk else None,
        ats_keywords=rk.ats_keywords if rk else None,
        match_label=rk.match_label if rk else None,
        match_signals=sig,
        apply_type=job.apply_type or "external",
        source_confidence=sources_meta.confidence_label(job.source),
        open_status=job.open_status or "open",
        company_tier=tier,
        watchlisted=watchlisted or bool(sig.get("watchlisted")),
        saved=bool(rk.saved) if rk else False,
        hidden=bool(rk.hidden) if rk else False,
        status=rk.status if rk else "new",
        auto_apply=job.auto_apply,
        applied_manually_at=rk.applied_manually_at if rk else None,
    )


def _user_watchlist_norms(db: Session, user_id: str, priority: str = "prioritize") -> set:
    rows = (
        db.query(models.WatchlistCompany.company_norm)
        .filter(models.WatchlistCompany.user_id == user_id,
                models.WatchlistCompany.priority == priority)
        .all()
    )
    return {r[0] for r in rows}


@router.get("", response_model=JobListOut)
def list_jobs(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
    q: Optional[str] = Query(None, description="Free-text search on title/company"),
    source: Optional[str] = None,
    min_rank: Optional[int] = None,
    status: Optional[str] = None,
    remote_only: bool = False,
    top_only: bool = Query(False, description="Only top-tier companies"),
    watchlist_only: bool = False,
    saved_only: bool = False,
    include_hidden: bool = False,
    include_closed: bool = False,
    match_level: Optional[str] = Query(
        None, pattern="^(excellent|good|maybe|not_recommended)$"
    ),
    posted_within_days: Optional[int] = Query(None, ge=1, le=365),
    sort: str = Query("rank", pattern="^(rank|recent)$"),
    limit: int = Query(50, le=200),
    offset: int = 0,
):
    """Jobs ranked for the current user, best first (or most recent)."""
    qry = db.query(models.Job, models.Ranking).join(
        models.Ranking,
        and_(models.Ranking.job_id == models.Job.id, models.Ranking.user_id == user.id),
    )
    if not include_hidden:
        qry = qry.filter(models.Ranking.hidden.is_(False))
    if not include_closed:
        qry = qry.filter(models.Job.open_status != "closed")
    if q:
        like = f"%{q.lower()}%"
        qry = qry.filter(
            or_(
                models.Job.title.ilike(like),
                models.Job.company.ilike(like),
                models.Job.description.ilike(like),
            )
        )
    if source:
        qry = qry.filter(models.Job.source == source)
    if min_rank is not None:
        qry = qry.filter(models.Ranking.rank_score >= min_rank)
    if status:
        qry = qry.filter(models.Ranking.status == status)
    if match_level:
        qry = qry.filter(models.Ranking.match_label == match_level)
    if remote_only:
        qry = qry.filter(models.Job.remote.is_(True))
    if saved_only:
        qry = qry.filter(models.Ranking.saved.is_(True))
    if top_only:
        from app.services.ranking import TOP_COMPANIES

        qry = qry.filter(
            or_(*[models.Job.company.ilike(f"%{c}%") for c in TOP_COMPANIES])
        )

    watch_norms = _user_watchlist_norms(db, user.id)
    if watchlist_only:
        if not watch_norms:
            return JobListOut(items=[], total=0)
        qry = qry.filter(
            or_(*[models.Job.company.ilike(f"%{n}%") for n in watch_norms])
        )
    if posted_within_days:
        cutoff = dt.datetime.utcnow() - dt.timedelta(days=posted_within_days)
        qry = qry.filter(
            func.coalesce(models.Job.posted_at, models.Job.discovered_at) >= cutoff
        )

    total = qry.count()
    if sort == "recent":
        order = (
            func.coalesce(models.Job.posted_at, models.Job.discovered_at).desc(),
            models.Ranking.rank_score.desc().nullslast(),
        )
    else:
        order = (
            models.Ranking.rank_score.desc().nullslast(),
            models.Job.discovered_at.desc(),
        )
    rows = qry.order_by(*order).offset(offset).limit(limit).all()
    overrides = user_context.load_company_overrides(db)
    items = []
    for j, rk in rows:
        norm = company_quality.normalize(j.company)
        items.append(
            _job_out(
                j,
                rk,
                tier=company_quality.tier_for(j.company, overrides),
                watchlisted=norm in watch_norms,
            )
        )
    return JobListOut(items=items, total=total)


def _clear_rankings(db: Session, user_id: str, scope: str) -> int:
    """Delete the user's rankings so they re-score from the shared pool.

    NEVER deletes work/intent the user invested: tailored, applied, or saved
    rows always survive. scope='ranked' additionally preserves hidden rows
    (so 'Not relevant' / 'Hide company' choices stick); scope='all' clears
    hidden too (a full re-evaluation, but still keeps saved/tailored/applied).
    Returns the number of rows removed."""
    q = db.query(models.Ranking).filter(
        models.Ranking.user_id == user_id,
        models.Ranking.status.notin_(_PROTECTED_STATUSES),
        models.Ranking.saved.is_(False),
    )
    if scope != "all":
        q = q.filter(models.Ranking.hidden.is_(False))
    return q.delete(synchronize_session=False)


@router.post("/reset-rankings", response_model=RerankResponse)
def reset_rankings(
    scope: str = Query("ranked", pattern="^(ranked|all)$"),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_verified_user),
):
    """Clear THIS user's rankings so the next run scores jobs fresh. Does not
    re-run the pipeline. scope=ranked (default) preserves tailored/applied jobs."""
    cleared = _clear_rankings(db, user.id, scope)
    db.commit()
    log.info(f"Reset rankings for {user.id[:8]}: cleared={cleared} scope={scope}")
    return RerankResponse(status="reset", cleared=cleared)


@router.post("/rerank", response_model=RerankResponse, dependencies=[Depends(_run_rl)])
def rerank(
    background_tasks: BackgroundTasks,
    scope: str = Query("ranked", pattern="^(ranked|all)$"),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_verified_user),
):
    """Clear THIS user's existing rankings, then kick a fresh rank-only run in the
    background (re-scores the current pool against your résumé + current mode)."""
    if not _active_resume_exists(db, user.id):
        raise HTTPException(400, "Upload your résumé first (Settings → résumé).")
    cleared = _clear_rankings(db, user.id, scope)
    db.commit()
    log.info(f"Rerank requested by {user.id[:8]}: cleared={cleared} scope={scope}")
    background_tasks.add_task(run_pipeline, "manual", user.id)
    return RerankResponse(status="started", cleared=cleared)


def _active_resume_exists(db: Session, user_id: str) -> bool:
    return (
        db.query(models.Resume.id)
        .filter(models.Resume.user_id == user_id, models.Resume.is_active.is_(True))
        .first()
        is not None
    )


@router.get("/{job_id}", response_model=JobOut)
def get_job(
    job_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    job = db.get(models.Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    rk = db.query(models.Ranking).filter_by(user_id=user.id, job_id=job_id).first()
    return _job_out(job, rk)


@router.post("/{job_id}/mark-applied", response_model=JobOut)
def mark_applied(
    job_id: str,
    payload: Optional[MarkAppliedRequest] = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_verified_user),
):
    """Record that the current user applied to this job (by hand)."""
    job = db.get(models.Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    when = (payload.applied_at if payload else None) or dt.datetime.utcnow()

    rk = db.query(models.Ranking).filter_by(user_id=user.id, job_id=job_id).first()
    if rk is None:
        rk = models.Ranking(user_id=user.id, job_id=job_id)
        db.add(rk)
    rk.status = "applied"
    rk.applied_manually_at = when

    app_row = (
        db.query(models.Application)
        .filter_by(user_id=user.id, job_id=job_id)
        .order_by(models.Application.created_at.desc())
        .first()
    )
    if app_row is None:
        app_row = models.Application(user_id=user.id, job_id=job_id, attempts=0)
        db.add(app_row)
    app_row.manual = True
    app_row.status = "submitted"
    app_row.submitted_at = when

    db.commit()
    db.refresh(job)
    if payload and payload.note:
        log.info(f"Manual apply note for {job.company} – {job.title}: {payload.note}")
    rk = db.query(models.Ranking).filter_by(user_id=user.id, job_id=job_id).first()
    return _job_out(job, rk)


@router.post("/{job_id}/feedback", response_model=JobOut)
def feedback(
    job_id: str,
    payload: FeedbackRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_verified_user),
):
    """Record a feedback action. The signals feed back into THIS user's ranking:
      • save / unsave     → keep in 'Saved'; protected from re-rank cleanup.
      • not_relevant      → hide this job + downrank similar titles in future runs.
      • hide_company      → hide all current + future jobs from this company.
      • more_like_this    → boost similar titles in future runs.
    """
    job = db.get(models.Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    rk = db.query(models.Ranking).filter_by(user_id=user.id, job_id=job_id).first()
    if rk is None:
        rk = models.Ranking(user_id=user.id, job_id=job_id)
        db.add(rk)

    action = payload.action
    norm = company_quality.normalize(job.company)
    terms = user_context.title_terms(job.title)

    if action == "save":
        rk.saved = True
    elif action == "unsave":
        rk.saved = False
    elif action == "not_relevant":
        rk.hidden = True
    elif action == "hide_company":
        rk.hidden = True
        # Hide every current ranking for this company (match on normalized name).
        pairs = (
            db.query(models.Ranking, models.Job)
            .join(models.Job, models.Job.id == models.Ranking.job_id)
            .filter(models.Ranking.user_id == user.id)
            .all()
        )
        for r, j in pairs:
            if company_quality.normalize(j.company) == norm:
                r.hidden = True

    db.add(
        models.JobFeedback(
            user_id=user.id,
            job_id=job_id,
            action=action,
            company_norm=norm if action == "hide_company" else None,
            terms=terms,
        )
    )
    db.commit()
    db.refresh(job)
    rk = db.query(models.Ranking).filter_by(user_id=user.id, job_id=job_id).first()
    return _job_out(job, rk)
