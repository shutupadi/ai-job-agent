"""
Guest (pre-signup) résumé sessions.

A visitor can upload + parse a résumé without an account. We store the parsed
profile against an unguessable token for a limited time, show them a preview, and
attach it to their account at signup. No LLM cost is spent on guests — the
"sample matches" teaser uses the existing deterministic relevance scorer over the
already-fetched job pool, so it's free and abuse-resistant.
"""

from __future__ import annotations

import datetime as dt
import secrets
from typing import List, Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.db import models
from app.services import relevance
from app.utils.logger import log


def _now() -> dt.datetime:
    return dt.datetime.utcnow()


def create_session(
    db: Session, filename: Optional[str], raw_text: str, parsed_json: dict
) -> models.GuestSession:
    gs = models.GuestSession(
        token=secrets.token_urlsafe(32),
        filename=filename,
        raw_text=(raw_text or "")[:20000],
        parsed_json=parsed_json,
        expires_at=_now() + dt.timedelta(hours=settings.guest_session_ttl_hours),
    )
    db.add(gs)
    db.flush()
    return gs


def get_active(db: Session, token: str) -> Optional[models.GuestSession]:
    if not token:
        return None
    gs = db.query(models.GuestSession).filter(models.GuestSession.token == token).first()
    if not gs or gs.claimed or gs.expires_at < _now():
        return None
    return gs


def cleanup_expired(db: Session) -> int:
    """Delete expired or claimed-and-old guest sessions. Returns rows removed."""
    cutoff = _now()
    n = (
        db.query(models.GuestSession)
        .filter(models.GuestSession.expires_at < cutoff)
        .delete(synchronize_session=False)
    )
    if n:
        log.info(f"Cleaned up {n} expired guest session(s)")
    return n


def sample_matches(db: Session, parsed_json: dict, limit: int = 5) -> List[dict]:
    """Cheap teaser: top jobs from the existing pool by deterministic relevance
    (NO LLM). Returns [] gracefully if the pool is empty."""
    try:
        terms = relevance.candidate_terms(parsed_json)
        technical = relevance.role_is_technical(parsed_json, terms)
        jobs = (
            db.query(models.Job)
            .filter(models.Job.description != "")
            .order_by(models.Job.discovered_at.desc())
            .limit(400)
            .all()
        )
        scored = []
        for j in jobs:
            if relevance.is_wrong_direction(technical, j.title):
                continue
            s = relevance.relevance_score(terms, technical, j.title, j.description)
            if s > 0:
                scored.append((s, j))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            {
                "title": j.title,
                "company": j.company,
                "location": j.location,
                "remote": j.remote,
                "url": j.url,
            }
            for _, j in scored[:limit]
        ]
    except Exception as e:  # noqa: BLE001
        log.warning(f"Guest sample_matches failed: {e}")
        return []
