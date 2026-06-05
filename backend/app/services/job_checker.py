"""
Lightweight closed-job detection.

Periodically probes a bounded set of postings (saved → recent, least-recently
checked first) and marks `open_status='closed'` when the URL is gone (404/410).
Conservative by design: only an explicit "gone" closes a job; network errors or
ambiguous responses leave the status untouched (no false closes).
"""

from __future__ import annotations

import datetime as dt
from typing import Optional

import httpx
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.config import settings
from app.db import models
from app.db.session import session_scope
from app.utils.logger import log

# Text markers some ATS return with a 200 when a role is filled/removed.
_CLOSED_MARKERS = (
    "no longer accepting applications",
    "this position has been filled",
    "this job is no longer available",
    "position is no longer available",
    "job posting not found",
    "the page you were looking for doesn",
)


def _probe(client: httpx.Client, url: str) -> Optional[str]:
    """Return 'closed' | 'open' | None (unknown — leave as-is)."""
    if not url:
        return None
    try:
        r = client.head(url, follow_redirects=True)
        # Some servers don't implement HEAD — fall back to a light GET.
        if r.status_code in (403, 405, 501):
            r = client.get(url, follow_redirects=True)
        if r.status_code in (404, 410):
            return "closed"
        if r.status_code >= 200 and r.status_code < 300:
            body = ""
            if r.request.method == "GET":
                body = (r.text or "")[:4000].lower()
            else:
                # cheap GET only to scan for explicit "closed" markers
                try:
                    body = (client.get(url, follow_redirects=True).text or "")[:4000].lower()
                except Exception:
                    body = ""
            if any(m in body for m in _CLOSED_MARKERS):
                return "closed"
            return "open"
        return None  # 3xx loop / 5xx / odd → don't decide
    except Exception:
        return None


def check_jobs(db: Session, limit: Optional[int] = None) -> dict:
    """Probe up to `limit` jobs (saved + recent, oldest-checked first)."""
    limit = limit or settings.job_check_max
    now = dt.datetime.utcnow()

    saved_ids = {
        r[0]
        for r in db.query(models.Ranking.job_id)
        .filter(models.Ranking.saved.is_(True))
        .all()
    }
    jobs = (
        db.query(models.Job)
        .filter(models.Job.open_status != "closed")
        .order_by(
            models.Job.last_checked_at.is_(None).desc(),  # never-checked first
            models.Job.last_checked_at.asc(),
            models.Job.discovered_at.desc(),
        )
        .limit(limit)
        .all()
    )
    # Make sure saved jobs are always included even if not in the recent slice.
    if saved_ids:
        extra = (
            db.query(models.Job)
            .filter(models.Job.id.in_(saved_ids), models.Job.open_status != "closed")
            .all()
        )
        seen = {j.id for j in jobs}
        jobs.extend(j for j in extra if j.id not in seen)

    checked = closed = 0
    with httpx.Client(timeout=10, headers={"User-Agent": "Mozilla/5.0 (job-agent liveness check)"}) as client:
        for job in jobs:
            verdict = _probe(client, job.url)
            job.last_checked_at = now
            checked += 1
            if verdict == "closed":
                job.open_status = "closed"
                closed += 1
            elif verdict == "open":
                job.open_status = "open"
    log.info(f"Closed-job check: probed {checked}, marked closed {closed}")
    return {"checked": checked, "closed": closed}


def run_check() -> dict:
    if not settings.job_check_enabled:
        return {"checked": 0, "closed": 0, "skipped": True}
    with session_scope() as db:
        return check_jobs(db)
