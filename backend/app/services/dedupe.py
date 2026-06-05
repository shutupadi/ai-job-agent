"""
Dedupe & persist new jobs.

A job is considered duplicate if:
  - same (source, external_id), OR
  - same url_hash (so the same posting cross-listed across sources still
    deduplicates).
"""

from __future__ import annotations

import datetime as dt
from typing import Iterable, List, Tuple

from sqlalchemy.orm import Session

from app.db import models
from app.sources.base import RawJob
from app.utils.logger import log


def _parse_dt(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        # accept both ISO and epoch-ms
        if value.isdigit() and len(value) >= 10:
            ts = int(value)
            if ts > 10_000_000_000:  # ms
                ts = ts / 1000
            return dt.datetime.utcfromtimestamp(ts)
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def upsert_jobs(db: Session, raws: Iterable[RawJob]) -> Tuple[List[models.Job], int]:
    """Returns (new_jobs, total_seen)."""
    new_jobs: List[models.Job] = []
    seen = 0

    # Pre-load existing keys so we don't query per-row
    existing_keys = {
        (s, eid)
        for s, eid in db.query(models.Job.source, models.Job.external_id).all()
    }
    existing_hashes = {
        h for (h,) in db.query(models.Job.url_hash).all()
    }

    for r in raws:
        seen += 1
        key = (r.source, r.external_id)
        if key in existing_keys or r.url_hash in existing_hashes:
            continue
        job = models.Job(
            source=r.source,
            external_id=r.external_id,
            url=r.url,
            url_hash=r.url_hash,
            title=r.title,
            company=r.company,
            location=r.location,
            remote=r.remote,
            department=r.department,
            description=r.description,
            salary_text=r.salary_text,
            posted_at=_parse_dt(r.posted_at),
            auto_apply=r.auto_apply,
            apply_type=getattr(r, "apply_type", "external"),
            raw=r.raw,
            status="new",
        )
        db.add(job)
        new_jobs.append(job)
        existing_keys.add(key)
        existing_hashes.add(r.url_hash)

    db.flush()
    log.info(f"upsert_jobs: seen={seen}, new={len(new_jobs)}")
    return new_jobs, seen
