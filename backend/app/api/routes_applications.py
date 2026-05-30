"""Application endpoints (per-user) — list, status updates, approve."""

from __future__ import annotations

import datetime as dt
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.db import models
from app.db.session import get_db
from app.schemas.schemas import (
    ApplicationListOut,
    ApplicationOut,
    ApplicationStatusUpdate,
)

router = APIRouter()


_VALID_STATES = {
    "queued",
    "awaiting_approval",
    "manual_pending",
    "submitted",
    "failed",
    "interview",
    "rejected",
    "offer",
}


def _owned(db: Session, app_id: str, user: models.User) -> models.Application:
    row = db.get(models.Application, app_id)
    if not row or row.user_id != user.id:
        raise HTTPException(404, "Not found")
    return row


@router.get("", response_model=ApplicationListOut)
def list_applications(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
    status: Optional[str] = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
):
    qry = db.query(models.Application).filter(models.Application.user_id == user.id)
    if status:
        qry = qry.filter(models.Application.status == status)
    total = qry.count()
    items = (
        qry.order_by(models.Application.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return ApplicationListOut(
        items=[ApplicationOut.model_validate(i) for i in items], total=total
    )


@router.get("/{app_id}", response_model=ApplicationOut)
def get_application(
    app_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    return ApplicationOut.model_validate(_owned(db, app_id, user))


@router.patch("/{app_id}/status", response_model=ApplicationOut)
def update_status(
    app_id: str,
    payload: ApplicationStatusUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    row = _owned(db, app_id, user)
    if payload.status not in _VALID_STATES:
        raise HTTPException(400, f"Invalid status. Must be one of {sorted(_VALID_STATES)}")
    row.status = payload.status
    if payload.status == "submitted" and not row.submitted_at:
        row.submitted_at = dt.datetime.utcnow()
    db.commit()
    db.refresh(row)
    return ApplicationOut.model_validate(row)


@router.post("/{app_id}/approve", response_model=ApplicationOut)
def approve(
    app_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    row = _owned(db, app_id, user)
    if row.status != "awaiting_approval":
        raise HTTPException(400, "Application is not awaiting approval")
    row.approved_at = dt.datetime.utcnow()
    row.status = "submitted"
    row.submitted_at = dt.datetime.utcnow()
    db.commit()
    db.refresh(row)
    return ApplicationOut.model_validate(row)
