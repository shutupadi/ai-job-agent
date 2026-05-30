"""
End-to-end pipeline (multi-user).

Stages:
  1. fetch     — pull RawJobs from every enabled source (SHARED pool).
  1b. geo gate — keep India / remote / sponsored-international only.
  1c. exp gate — keep fresher / entry-level only.
  2. ingest    — dedupe + persist into the shared `jobs` pool.
  3. rank      — for each target user (with an uploaded résumé), score their
                 not-yet-ranked jobs against THEIR résumé into `rankings`.

Approval-only: nothing is auto-applied. Users review their shortlist, tailor on
demand, apply themselves, and mark applied.

Callable from:
  - FastAPI POST /api/runs/trigger   (ranks just the current user)
  - APScheduler every 12h            (ranks all active users)
  - CLI: python -m app.scheduler.jobs run-once
"""

from __future__ import annotations

import datetime as dt
import time
from typing import List, Optional, Tuple

from app.config import settings
from app.db import models
from app.db.session import session_scope
from app.services import experience_filter, geo_filter, ranking, resume_engine
from app.services.dedupe import upsert_jobs
from app.services.notifier import notify_summary
from app.sources.base import RawJob
from app.sources.registry import enabled_sources
from app.utils.logger import log


def _fetch_all() -> List[RawJob]:
    out: List[RawJob] = []
    for src in enabled_sources():
        try:
            out.extend(list(src.fetch()))
        except Exception as e:
            log.error(f"Source {src.name} failed: {e}")
    return out


def prune_old_jobs(days: int) -> int:
    """Delete jobs older than `days` that nobody acted on (no application, and no
    ranking marked tailored/applied). Their stale rankings cascade-delete. Keeps
    the shared pool fresh + small. Returns the number deleted."""
    if days <= 0:
        return 0
    cutoff = dt.datetime.utcnow() - dt.timedelta(days=days)
    with session_scope() as db:
        protected_apps = db.query(models.Application.job_id).filter(
            models.Application.job_id.isnot(None)
        )
        protected_rk = db.query(models.Ranking.job_id).filter(
            models.Ranking.status.in_(("tailored", "applied"))
        )
        ids = [
            row[0]
            for row in db.query(models.Job.id)
            .filter(models.Job.discovered_at < cutoff)
            .filter(models.Job.id.notin_(protected_apps))
            .filter(models.Job.id.notin_(protected_rk))
            .all()
        ]
        deleted = 0
        for i in range(0, len(ids), 500):
            chunk = ids[i : i + 500]
            deleted += (
                db.query(models.Job)
                .filter(models.Job.id.in_(chunk))
                .delete(synchronize_session=False)
            )
        return deleted


def rank_jobs_for_user(user_id: str, resume_json: dict, limit: int) -> int:
    """Rank up to `limit` jobs this user has NO ranking for yet, against their
    résumé. Budget-aware, rate-limited, circuit-broken. Returns count ranked."""
    with session_scope() as db:
        already = db.query(models.Ranking.job_id).filter(models.Ranking.user_id == user_id)
        new_ids = [
            j.id
            for j in db.query(models.Job)
            .filter(models.Job.id.notin_(already))
            .filter(models.Job.description != "")
            .order_by(models.Job.discovered_at.desc())
            .limit(limit)
            .all()
        ]
    if not new_ids:
        return 0
    log.info(f"Ranking up to {len(new_ids)} jobs for user {user_id[:8]}")
    ranked = 0
    consecutive_failures = 0
    for jid in new_ids:
        try:
            with session_scope() as db:
                job = db.get(models.Job, jid)
                ranking.rank_job_for_user(db, user_id, resume_json, job)
                ranked += 1
                consecutive_failures = 0
        except Exception as e:
            consecutive_failures += 1
            log.warning(f"Rank failed ({user_id[:8]}/{jid[:8]}): {e}")
            if consecutive_failures >= settings.rank_circuit_breaker:
                log.error("Circuit breaker tripped — stopping ranking for this user.")
                break
        time.sleep(settings.llm_call_delay_seconds)
    return ranked


def _target_users(user_id: Optional[str]) -> List[Tuple[str, dict]]:
    """(user_id, résumé_json) for the users to rank this run. A specific user if
    given, else every active user — only those who've uploaded a résumé."""
    with session_scope() as db:
        if user_id:
            u = db.get(models.User, user_id)
            users = [u] if u and u.is_active else []
        else:
            users = db.query(models.User).filter(models.User.is_active.is_(True)).all()
        targets: List[Tuple[str, dict]] = []
        for u in users:
            rj = resume_engine.load_user_resume(db, u.id)
            if rj:
                targets.append((u.id, rj))
        return targets


def run_pipeline(trigger: str = "manual", user_id: Optional[str] = None) -> str:
    """Fetch + ingest the shared pool, then rank for the target user(s).
    Returns the Run id."""
    with session_scope() as db:
        run = models.Run(trigger=trigger, status="running")
        db.add(run)
        db.flush()
        run_id = run.id
        log.info(f"Run {run_id} started ({trigger}, user={user_id or 'ALL'})")

    log_buf: List[str] = []

    # ── 1. fetch + gates + ingest (shared pool) ──
    raws = _fetch_all()
    kept, geo_dropped = geo_filter.filter_rawjobs(raws)
    kept, exp_dropped = experience_filter.filter_rawjobs(kept)
    with session_scope() as db:
        run = db.get(models.Run, run_id)
        run.jobs_found = len(raws)
        new_jobs, _ = upsert_jobs(db, kept)
        run.jobs_new = len(new_jobs)
        log_buf.append(
            f"fetched={len(raws)} kept={len(kept)} geo_dropped={geo_dropped} "
            f"exp_dropped={exp_dropped} new={len(new_jobs)}"
        )

    # ── 2. per-user ranking ──
    targets = _target_users(user_id)
    total_ranked = 0
    users_ranked = 0
    for uid, resume_json in targets:
        n = rank_jobs_for_user(uid, resume_json, settings.max_ranks_per_user)
        total_ranked += n
        if n:
            users_ranked += 1

    # ── 2b. cleanup: free up old jobs nobody acted on ──
    pruned = prune_old_jobs(settings.job_retention_days)
    if pruned:
        log.info(f"Pruned {pruned} old jobs (>{settings.job_retention_days}d, unused)")

    # ── 3. finalise ──
    with session_scope() as db:
        run = db.get(models.Run, run_id)
        run.ranked = total_ranked
        run.finished_at = dt.datetime.utcnow()
        run.status = "success"
        log_buf.append(f"users_ranked={users_ranked} total_ranked={total_ranked}")
        run.log = "\n".join(log_buf)
        run.summary = (
            f"Run {run_id[:8]} ({trigger})\n"
            f"  jobs found:   {run.jobs_found}\n"
            f"  new jobs:     {run.jobs_new}\n"
            f"  users ranked: {users_ranked} (of {len(targets)} with résumés)\n"
            f"  rankings:     {total_ranked}\n"
            f"  pruned old:   {pruned}\n"
        )
        log.info(run.summary)

    try:
        notify_summary(run_id)
    except Exception as e:
        log.warning(f"Notification failed: {e}")

    return run_id
