"""Dashboard endpoint — per-user summary for the home page."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.api.routes_jobs import _job_out
from app.auth.deps import get_current_user
from app.config import settings
from app.db import models
from app.db.session import get_db
from app.schemas.schemas import DashboardSummary, RunOut

router = APIRouter()


@router.get("/summary", response_model=DashboardSummary)
def summary(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    R = models.Ranking
    threshold = settings.min_rank_to_apply
    base = db.query(R).filter(R.user_id == user.id)

    total_ranked = base.count()
    ranked = base.filter(R.rank_score.isnot(None)).count()
    shortlisted = (
        base.filter(R.status.in_(("ranked", "tailored")))
        .filter(R.rank_score >= threshold)
        .filter(R.applied_manually_at.is_(None))
        .count()
    )
    tailored = base.filter(R.status == "tailored").count()
    applied = base.filter(
        or_(R.status == "applied", R.applied_manually_at.isnot(None))
    ).count()

    apps = (
        db.query(models.Application)
        .filter(models.Application.user_id == user.id)
        .all()
    )
    submitted = sum(1 for a in apps if a.status == "submitted")
    failed = sum(1 for a in apps if a.status == "failed")
    awaiting = sum(1 for a in apps if a.status == "awaiting_approval")
    interview = sum(1 for a in apps if a.status == "interview")
    rejected = sum(1 for a in apps if a.status == "rejected")

    last_run = db.query(models.Run).order_by(models.Run.started_at.desc()).first()

    top = (
        db.query(models.Job, R)
        .join(R, and_(R.job_id == models.Job.id, R.user_id == user.id))
        .filter(R.rank_score.isnot(None))
        .order_by(R.rank_score.desc().nullslast())
        .limit(10)
        .all()
    )

    return DashboardSummary(
        total_jobs=total_ranked,
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
        top_jobs=[_job_out(j, rk) for j, rk in top],
    )
