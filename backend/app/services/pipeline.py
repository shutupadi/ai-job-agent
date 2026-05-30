"""
End-to-end pipeline (multi-user, parallel-safe).

- Scheduler (no user_id): fetch every source → geo gate → ingest into the SHARED
  pool → rank for every user with a résumé → prune old jobs.
- User trigger (user_id): RANK-ONLY against the existing pool (cheap + safe for
  many concurrent users). It only fetches if the pool is stale AND no other fetch
  is already running (a process-wide lock), so 4-5 users can run in parallel
  without re-fetching or blowing memory.

Per-user fresher mode: if the user's experience_pref is 'fresher', we drop
senior / high-YOE jobs from THEIR candidate set before ranking (deterministic),
so a fresher never sees 7-year roles regardless of how the parser read the CV.
"""

from __future__ import annotations

import datetime as dt
import threading
import time
from typing import List, Optional, Tuple

from app.config import settings
from app.db import models
from app.db.session import session_scope
from app.services import experience_filter, geo_filter, ranking, relevance, resume_engine
from app.services.dedupe import upsert_jobs
from app.services.notifier import notify_summary
from app.sources.base import RawJob
from app.sources.registry import enabled_sources
from app.utils.logger import log

# Process-wide guards so concurrent triggers stay safe on a single instance.
_FETCH_LOCK = threading.Lock()          # at most one source-fetch at a time
_running_users: set[str] = set()        # users with a run already in flight
_running_lock = threading.Lock()


def _fetch_all() -> List[RawJob]:
    out: List[RawJob] = []
    for src in enabled_sources():
        try:
            out.extend(list(src.fetch()))
        except Exception as e:
            log.error(f"Source {src.name} failed: {e}")
    return out


def _pool_is_fresh(hours: int = 6, min_jobs: int = 60) -> bool:
    cutoff = dt.datetime.utcnow() - dt.timedelta(hours=hours)
    with session_scope() as db:
        return (
            db.query(models.Job).filter(models.Job.discovered_at >= cutoff).count()
            >= min_jobs
        )


def prune_old_jobs(days: int) -> int:
    """Delete jobs older than `days` that nobody acted on (no application, and no
    ranking marked tailored/applied). Stale rankings cascade-delete."""
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


def rank_jobs_for_user(
    user_id: str, resume_json: dict, limit: int, fresher: bool = False
) -> int:
    """Rank up to `limit` of this user's not-yet-ranked jobs against their résumé.
    In fresher mode, only entry-level jobs are considered."""
    # Pull a wide pool of not-yet-ranked jobs, then keep only the most
    # RÉSUMÉ-RELEVANT `limit` to spend LLM calls on (skips off-target sales/HR/etc.).
    pool_size = max(limit * 12, 300)
    with session_scope() as db:
        already = db.query(models.Ranking.job_id).filter(models.Ranking.user_id == user_id)
        cands = (
            db.query(models.Job)
            .filter(models.Job.id.notin_(already))
            .filter(models.Job.description != "")
            .order_by(models.Job.discovered_at.desc())
            .limit(pool_size)
            .all()
        )
        rows = [(j.id, j.title, j.description) for j in cands]

    if fresher:
        rows = [r for r in rows if experience_filter.is_fresher_friendly(r[1], r[2])]

    terms = relevance.candidate_terms(resume_json)
    technical = relevance.is_technical(terms)
    rows.sort(
        key=lambda r: relevance.relevance_score(terms, technical, r[1], r[2]),
        reverse=True,
    )
    new_ids = [r[0] for r in rows[:limit]]
    if not new_ids:
        return 0

    log.info(f"Ranking {len(new_ids)} jobs for user {user_id[:8]} (fresher={fresher})")
    ranked = 0
    consecutive_failures = 0
    for jid in new_ids:
        try:
            with session_scope() as db:
                job = db.get(models.Job, jid)
                ranking.rank_job_for_user(db, user_id, resume_json, job, fresher=fresher)
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


def _target_users(user_id: Optional[str]) -> List[Tuple[str, dict, bool]]:
    """(user_id, résumé_json, fresher_mode) for users to rank — only those with a
    résumé. fresher_mode comes from each user's experience_pref."""
    with session_scope() as db:
        if user_id:
            u = db.get(models.User, user_id)
            users = [u] if u and u.is_active else []
        else:
            users = db.query(models.User).filter(models.User.is_active.is_(True)).all()
        targets: List[Tuple[str, dict, bool]] = []
        for u in users:
            rj = resume_engine.load_user_resume(db, u.id)
            if rj:
                fresher = (u.experience_pref or "fresher").lower() == "fresher"
                targets.append((u.id, rj, fresher))
        return targets


def _do_fetch(run_id: str, log_buf: List[str]) -> None:
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


def run_pipeline(trigger: str = "manual", user_id: Optional[str] = None) -> str:
    """Returns the Run id (or '' if skipped because the user already has a run)."""
    if user_id:
        with _running_lock:
            if user_id in _running_users:
                log.info(f"User {user_id[:8]} already has a run in progress; skipping.")
                return ""
            _running_users.add(user_id)
    try:
        return _run_pipeline(trigger, user_id)
    finally:
        if user_id:
            with _running_lock:
                _running_users.discard(user_id)


def _run_pipeline(trigger: str, user_id: Optional[str]) -> str:
    with session_scope() as db:
        run = models.Run(trigger=trigger, status="running")
        db.add(run)
        db.flush()
        run_id = run.id
        log.info(f"Run {run_id} started ({trigger}, user={user_id or 'ALL'})")

    log_buf: List[str] = []

    # ── 1. fetch (scheduler always; user trigger only if pool stale) ──
    fetched = False
    want_fetch = (user_id is None) or (not _pool_is_fresh())
    if want_fetch:
        if _FETCH_LOCK.acquire(blocking=False):
            try:
                _do_fetch(run_id, log_buf)
                fetched = True
            finally:
                _FETCH_LOCK.release()
        else:
            log_buf.append("fetch skipped (another fetch in progress)")
    else:
        log_buf.append("fetch skipped (pool fresh)")

    # ── 2. per-user ranking ──
    targets = _target_users(user_id)
    total_ranked = 0
    users_ranked = 0
    for uid, resume_json, fresher in targets:
        n = rank_jobs_for_user(uid, resume_json, settings.max_ranks_per_user, fresher=fresher)
        total_ranked += n
        if n:
            users_ranked += 1

    # ── 2b. cleanup (only when we fetched, i.e. scheduler / stale refresh) ──
    pruned = prune_old_jobs(settings.job_retention_days) if fetched else 0
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
