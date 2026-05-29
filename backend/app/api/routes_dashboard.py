"""Dashboard endpoint — single payload used by the home page."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.config import settings
from app.db import models
from app.db.session import get_db
from app.schemas.schemas import DashboardSummary, JobOut, RunOut

router = APIRouter()


@router.get("/summary", response_model=DashboardSummary)
def summary(db: Session = Depends(get_db)):
    Job = models.Job
    total_jobs = db.query(Job).count()
    threshold = settings.min_rank_to_apply

    ranked = db.query(Job).filter(Job.rank_score.isnot(None)).count()
    # Shortlist = ranked/tailored jobs at/above the threshold the user still
    # needs to act on (not yet applied).
    shortlisted = (
        db.query(Job)
        .filter(Job.status.in_(("ranked", "tailored")))
        .filter(Job.rank_score >= threshold)
        .filter(Job.applied_manually_at.is_(None))
        .count()
    )
    tailored = db.query(Job).filter(Job.status == "tailored").count()
    applied = (
        db.query(Job)
        .filter(or_(Job.status == "applied", Job.applied_manually_at.isnot(None)))
        .count()
    )

    apps = db.query(models.Application).all()
    submitted = sum(1 for a in apps if a.status == "submitted")
    failed = sum(1 for a in apps if a.status == "failed")
    awaiting = sum(1 for a in apps if a.status == "awaiting_approval")
    interview = sum(1 for a in apps if a.status == "interview")
    rejected = sum(1 for a in apps if a.status == "rejected")

    last_run = db.query(models.Run).order_by(models.Run.started_at.desc()).first()
    top = (
        db.query(Job)
        .filter(Job.rank_score.isnot(None))
        .order_by(Job.rank_score.desc().nullslast())
        .limit(10)
        .all()
    )
    return DashboardSummary(
        total_jobs=total_jobs,
        ranked=ranked,
        shortlisted=shortlisted,
        tailored=tailored,
        applied=applied,
        apply_mode=settings.apply_mode,
        min_rank_to_apply=threshold,
        llm_model=settings.active_llm_model,
        total_applications=len(apps),
        submitted=submitted,
        failed=failed,
        awaiting_approval=awaiting,
        interviews=interview,
        rejected=rejected,
        last_run=RunOut.model_validate(last_run) if last_run else None,
        top_jobs=[JobOut.model_validate(t) for t in top],
    )
