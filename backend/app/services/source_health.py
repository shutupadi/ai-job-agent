"""
Per-source health tracking.

After each fetch we upsert a SourceHealth row per source: when it last ran, when
it last succeeded, how many postings it returned + how many were new, cumulative
failures, and the last error. Surfaced read-only in the admin dashboard so an
operator can see at a glance which adapters are healthy vs broken.
"""

from __future__ import annotations

import datetime as dt
from typing import Dict

from sqlalchemy.orm import Session

from app.db import models
from app.db.session import session_scope


def record(stats: Dict[str, dict]) -> None:
    """stats: {source_name: {"found": int, "added": int, "ok": bool, "error": str|None}}"""
    if not stats:
        return
    now = dt.datetime.utcnow()
    with session_scope() as db:
        for name, s in stats.items():
            row = db.get(models.SourceHealth, name)
            if row is None:
                row = models.SourceHealth(source=name)
                db.add(row)
            row.last_run_at = now
            row.total_runs = (row.total_runs or 0) + 1
            row.jobs_found = int(s.get("found", 0))
            row.jobs_added = int(s.get("added", 0))
            if s.get("ok"):
                row.last_success_at = now
                row.last_error = None
            else:
                row.failures = (row.failures or 0) + 1
                row.last_error = (s.get("error") or "unknown error")[:2000]


def all_health(db: Session):
    return db.query(models.SourceHealth).order_by(models.SourceHealth.source).all()
