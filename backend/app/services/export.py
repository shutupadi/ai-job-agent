"""
Shortlist export.

In the default APPLY_MODE=approval, NOTHING is auto-applied — every source is a
discovery source and the user works the ranked shortlist by hand. This module
produces that worklist:

  - `shortlist_query()`  : the canonical DB query for "ranked jobs at/above the
                           threshold that I haven't applied to yet".
  - `shortlist_csv()`    : that worklist serialised to CSV text.
  - `write_daily_export()`: persist today's CSV under storage/exports/ and
                            return (path, row_count). Called at the end of a run.

`manual_only` controls whether the worklist is restricted to non-auto-apply
sources. In legacy `auto` mode the pipeline auto-submits ATS sources, so the
worklist defaults to the manual subset (auto_apply=False). In `approval` mode
everything is manual, so the worklist includes all sources.

`rank_only_query` / `rank_only_csv` are kept as thin back-compat wrappers.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
from pathlib import Path
from typing import List, Optional, Tuple

from sqlalchemy.orm import Query, Session

from app.config import settings
from app.db import models
from app.utils.logger import log

_COLUMNS = ["rank_score", "company", "title", "location", "remote", "source", "status", "url"]


def _default_manual_only() -> bool:
    """In auto mode the worklist is just the manual subset; in approval mode
    every source is manual, so include all sources."""
    return settings.apply_mode.lower() == "auto"


def shortlist_query(
    db: Session,
    min_rank: Optional[int] = None,
    manual_only: Optional[bool] = None,
) -> Query:
    threshold = settings.min_rank_to_apply if min_rank is None else min_rank
    manual_only = _default_manual_only() if manual_only is None else manual_only
    q = (
        db.query(models.Job)
        .filter(models.Job.rank_score.isnot(None))
        .filter(models.Job.rank_score >= threshold)
        .filter(models.Job.status != "applied")
        .filter(models.Job.applied_manually_at.is_(None))
    )
    if manual_only:
        q = q.filter(models.Job.auto_apply.is_(False))
    return q.order_by(models.Job.rank_score.desc())


# Back-compat aliases (manual subset only) used by the older CSV endpoint.
def rank_only_query(db: Session, min_rank: Optional[int] = None) -> Query:
    return shortlist_query(db, min_rank=min_rank, manual_only=True)


def _rows(jobs: List[models.Job]) -> List[dict]:
    return [
        {
            "rank_score": j.rank_score,
            "company": j.company,
            "title": j.title,
            "location": j.location or "",
            "remote": "yes" if j.remote else "no",
            "source": j.source,
            "status": j.status,
            "url": j.url,
        }
        for j in jobs
    ]


def shortlist_csv(
    db: Session,
    min_rank: Optional[int] = None,
    manual_only: Optional[bool] = None,
) -> str:
    jobs = shortlist_query(db, min_rank, manual_only).all()
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_COLUMNS)
    writer.writeheader()
    writer.writerows(_rows(jobs))
    return buf.getvalue()


def rank_only_csv(db: Session, min_rank: Optional[int] = None) -> str:
    return shortlist_csv(db, min_rank=min_rank, manual_only=True)


def write_daily_export(db: Session) -> Tuple[Path, int]:
    jobs = shortlist_query(db).all()
    exports_dir = Path(settings.storage_dir) / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d")
    path = exports_dir / f"shortlist_{stamp}.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_COLUMNS)
        writer.writeheader()
        writer.writerows(_rows(jobs))
    log.info(f"Shortlist export: wrote {len(jobs)} jobs to {path}")
    return path, len(jobs)
