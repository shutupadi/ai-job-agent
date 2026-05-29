"""Job endpoints — list / get / search / mark-applied / rank-only export."""

from __future__ import annotations

import datetime as dt
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db import models
from app.db.session import get_db
from app.schemas.schemas import JobListOut, JobOut, MarkAppliedRequest
from app.services import export as export_svc
from app.utils.logger import log

router = APIRouter()


@router.get("", response_model=JobListOut)
def list_jobs(
    db: Session = Depends(get_db),
    q: Optional[str] = Query(None, description="Free-text search on title/company"),
    source: Optional[str] = None,
    min_rank: Optional[int] = None,
    status: Optional[str] = None,
    remote_only: bool = False,
    auto_apply: Optional[bool] = Query(
        None, description="true=auto-applicable only, false=rank-only (manual) only"
    ),
    limit: int = Query(50, le=200),
    offset: int = 0,
):
    qry = db.query(models.Job)
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
        qry = qry.filter(models.Job.rank_score >= min_rank)
    if status:
        qry = qry.filter(models.Job.status == status)
    if remote_only:
        qry = qry.filter(models.Job.remote.is_(True))
    if auto_apply is not None:
        qry = qry.filter(models.Job.auto_apply.is_(auto_apply))
    total = qry.count()
    items = (
        qry.order_by(models.Job.rank_score.desc().nullslast(), models.Job.discovered_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return JobListOut(items=[JobOut.model_validate(i) for i in items], total=total)


# NOTE: declared before "/{job_id}" so the literal path isn't captured as an id.
@router.get("/export/rank-only.csv")
def export_rank_only(
    db: Session = Depends(get_db),
    min_rank: Optional[int] = Query(None, description="Override MIN_RANK_TO_APPLY"),
):
    """CSV worklist of rank-only jobs (LinkedIn/Naukri/…) to apply to by hand."""
    csv_text = export_svc.rank_only_csv(db, min_rank=min_rank)
    stamp = dt.datetime.now().strftime("%Y%m%d")
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="rank_only_{stamp}.csv"'},
    )


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: str, db: Session = Depends(get_db)):
    job = db.get(models.Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return JobOut.model_validate(job)


@router.post("/{job_id}/mark-applied", response_model=JobOut)
def mark_applied(
    job_id: str,
    payload: Optional[MarkAppliedRequest] = None,
    db: Session = Depends(get_db),
):
    """Mark a (typically rank-only) job as applied-to manually.

    Flips the job to 'applied', stamps applied_manually_at, and ensures there's
    a submitted Application row flagged manual=True so dashboards stay accurate.
    """
    job = db.get(models.Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    when = (payload.applied_at if payload else None) or dt.datetime.utcnow()
    job.status = "applied"
    job.applied_manually_at = when

    app_row = (
        db.query(models.Application)
        .filter(models.Application.job_id == job_id)
        .order_by(models.Application.created_at.desc())
        .first()
    )
    if app_row is None:
        app_row = models.Application(job_id=job_id, attempts=0)
        db.add(app_row)
    app_row.manual = True
    app_row.status = "submitted"
    app_row.submitted_at = when

    db.commit()
    db.refresh(job)
    if payload and payload.note:
        log.info(f"Manual apply note for {job.company} – {job.title}: {payload.note}")
    return JobOut.model_validate(job)
