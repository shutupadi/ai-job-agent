"""
Per-user company watchlist.

prioritize → checked first by the fast watchlist scan + boosted in ranking
             (only when role fit is good — see scoring.py).
block      → never shown.
normal     → tracked but no boost.
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user, get_verified_user
from app.db import models
from app.db.session import get_db
from app.schemas.schemas import WatchlistCreate, WatchlistOut, WatchlistPatch
from app.services import company_quality

router = APIRouter()


def _out(w: models.WatchlistCompany) -> WatchlistOut:
    return WatchlistOut(id=w.id, company=w.company, priority=w.priority)


@router.get("", response_model=List[WatchlistOut])
def list_watchlist(
    db: Session = Depends(get_db), user: models.User = Depends(get_current_user)
):
    rows = (
        db.query(models.WatchlistCompany)
        .filter(models.WatchlistCompany.user_id == user.id)
        .order_by(models.WatchlistCompany.priority, models.WatchlistCompany.company)
        .all()
    )
    return [_out(w) for w in rows]


@router.post("", response_model=WatchlistOut, status_code=201)
def add_company(
    payload: WatchlistCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_verified_user),
):
    norm = company_quality.normalize(payload.company)
    if not norm:
        raise HTTPException(400, "Invalid company name.")
    existing = (
        db.query(models.WatchlistCompany)
        .filter_by(user_id=user.id, company_norm=norm)
        .first()
    )
    if existing:
        existing.priority = payload.priority
        existing.company = payload.company.strip()
        db.commit()
        db.refresh(existing)
        return _out(existing)
    w = models.WatchlistCompany(
        user_id=user.id,
        company=payload.company.strip(),
        company_norm=norm,
        priority=payload.priority,
    )
    db.add(w)
    db.commit()
    db.refresh(w)
    return _out(w)


@router.patch("/{item_id}", response_model=WatchlistOut)
def update_company(
    item_id: str,
    payload: WatchlistPatch,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_verified_user),
):
    w = db.get(models.WatchlistCompany, item_id)
    if not w or w.user_id != user.id:
        raise HTTPException(404, "Watchlist item not found")
    w.priority = payload.priority
    db.commit()
    db.refresh(w)
    return _out(w)


@router.delete("/{item_id}", status_code=204)
def remove_company(
    item_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_verified_user),
):
    w = db.get(models.WatchlistCompany, item_id)
    if not w or w.user_id != user.id:
        raise HTTPException(404, "Watchlist item not found")
    db.delete(w)
    db.commit()
    return None
