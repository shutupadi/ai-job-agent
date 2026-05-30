"""Job endpoints (per-user) — ranked list / get / mark-applied."""

from __future__ import annotations

import datetime as dt
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.db import models
from app.db.session import get_db
from app.schemas.schemas import JobListOut, JobOut, MarkAppliedRequest
from app.utils.logger import log

router = APIRouter()


def _job_out(job: models.Job, rk: Optional[models.Ranking]) -> JobOut:
    """Merge a shared Job with THIS user's Ranking into the API shape."""
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
        status=rk.status if rk else "new",
        auto_apply=job.auto_apply,
        applied_manually_at=rk.applied_manually_at if rk else None,
    )


@router.get("", response_model=JobListOut)
def list_jobs(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
    q: Optional[str] = Query(None, description="Free-text search on title/company"),
    source: Optional[str] = None,
    min_rank: Optional[int] = None,
    status: Optional[str] = None,
    remote_only: bool = False,
    limit: int = Query(50, le=200),
    offset: int = 0,
):
    """Jobs ranked for the current user, best first."""
    qry = db.query(models.Job, models.Ranking).join(
        models.Ranking,
        and_(models.Ranking.job_id == models.Job.id, models.Ranking.user_id == user.id),
    )
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
    if remote_only:
        qry = qry.filter(models.Job.remote.is_(True))

    total = qry.count()
    rows = (
        qry.order_by(
            models.Ranking.rank_score.desc().nullslast(),
            models.Job.discovered_at.desc(),
        )
        .offset(offset)
        .limit(limit)
        .all()
    )
    return JobListOut(items=[_job_out(j, rk) for j, rk in rows], total=total)


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
    user: models.User = Depends(get_current_user),
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
