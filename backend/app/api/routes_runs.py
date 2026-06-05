"""Run endpoints — trigger (for the current user) / list / get."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.auth.rate_limit import RateLimiter
from app.config import settings
from app.db import models
from app.db.session import get_db
from app.schemas.schemas import RunOut
from app.services.pipeline import run_pipeline

router = APIRouter()

_run_rl = RateLimiter("run", times=settings.rl_run_times, seconds=settings.rl_run_seconds)


@router.post("/trigger", dependencies=[Depends(_run_rl)])
def trigger(
    background_tasks: BackgroundTasks,
    user: models.User = Depends(get_current_user),
):
    """Kick the pipeline asynchronously: refresh the shared pool + rank for YOU.
    Returns immediately."""
    background_tasks.add_task(run_pipeline, "manual", user.id)
    return {"status": "started"}


@router.get("", response_model=List[RunOut])
def list_runs(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
    limit: int = 20,
):
    rows = (
        db.query(models.Run)
        .order_by(models.Run.started_at.desc())
        .limit(limit)
        .all()
    )
    return [RunOut.model_validate(r) for r in rows]


@router.get("/{run_id}", response_model=RunOut)
def get_run(
    run_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    row = db.get(models.Run, run_id)
    if not row:
        raise HTTPException(404, "Run not found")
    return RunOut.model_validate(row)
