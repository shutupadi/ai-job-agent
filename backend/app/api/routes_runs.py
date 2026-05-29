"""Run endpoints — trigger / list / get."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from app.db import models
from app.db.session import get_db
from app.schemas.schemas import RunOut
from app.services.pipeline import run_pipeline

router = APIRouter()


@router.post("/trigger")
def trigger(background_tasks: BackgroundTasks):
    """Kick the full pipeline asynchronously. Returns immediately."""
    background_tasks.add_task(run_pipeline, "manual")
    return {"status": "started"}


@router.get("", response_model=List[RunOut])
def list_runs(db: Session = Depends(get_db), limit: int = 20):
    rows = (
        db.query(models.Run)
        .order_by(models.Run.started_at.desc())
        .limit(limit)
        .all()
    )
    return [RunOut.model_validate(r) for r in rows]


@router.get("/{run_id}", response_model=RunOut)
def get_run(run_id: str, db: Session = Depends(get_db)):
    row = db.get(models.Run, run_id)
    if not row:
        from fastapi import HTTPException

        raise HTTPException(404, "Run not found")
    return RunOut.model_validate(row)
