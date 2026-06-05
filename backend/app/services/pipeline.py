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
from app.services import (
    alerts,
    company_quality,
    experience_filter,
    geo_filter,
    guest,
    job_checker,
    ranking,
    relevance,
    resume_engine,
    source_health,
    user_context,
)
from app.services.dedupe import upsert_jobs
from app.services.notifier import notify_summary
from app.sources.base import RawJob
from app.sources.registry import enabled_sources
from app.utils.logger import log

# Process-wide guards so concurrent triggers stay safe on a single instance.
_FETCH_LOCK = threading.Lock()          # at most one source-fetch at a time
_running_users: set[str] = set()        # users with a run already in flight
_running_lock = threading.Lock()


def _fetch_all() -> Tuple[List[RawJob], dict]:
    """Fetch every enabled source. Returns (all_raw_jobs, per_source_stats) where
    stats[name] = {found, ok, error} (added is filled in after dedupe)."""
    out: List[RawJob] = []
    stats: dict = {}
    for src in enabled_sources():
        try:
            jobs = list(src.fetch())
            out.extend(jobs)
            stats[src.name] = {"found": len(jobs), "added": 0, "ok": True, "error": None}
        except Exception as e:
            log.error(f"Source {src.name} failed: {e}")
            stats[src.name] = {"found": 0, "added": 0, "ok": False, "error": str(e)}
    return out, stats


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


def passes_prefilter(
    technical: bool,
    years: int,
    fresher: bool,
    title: str,
    description: str,
    *,
    ctx=None,
    company: str = "",
) -> bool:
    """Cheap per-user keep/drop decision applied BEFORE any LLM call:
      1. experience-level gate (fresher → entry-only; else level window),
      2. role-direction hard drop (a technical CV never sees sales/HR/etc.),
      3. (with ctx) blocked/hidden company, excluded keyword, blocked industry,
         and obvious spam/scam postings.
    """
    if not experience_filter.level_ok(title, description, years, fresher=fresher):
        return False
    if relevance.is_wrong_direction(technical, title):
        return False
    if ctx is not None:
        norm = company_quality.normalize(company)
        if norm in ctx.hidden_companies or ctx.watchlist.get(norm) == "block":
            return False
        blob = f"{title}\n{description}".lower()
        if any(str(k).lower().strip() and str(k).lower().strip() in blob for k in ctx.excluded_keywords):
            return False
        if any(str(k).lower().strip() and str(k).lower().strip() in blob for k in ctx.blocked_industries):
            return False
        if company_quality.is_suspicious(company, title, description):
            return False
    return True


def rank_jobs_for_user(
    user_id: str,
    resume_json: dict,
    limit: int,
    fresher: bool = False,
    watchlist_only: bool = False,
) -> int:
    """Rank up to `limit` of this user's not-yet-ranked jobs against their full
    career profile + preferences + watchlist + feedback (hybrid scoring).

    watchlist_only: only consider jobs at the user's prioritised companies (used
    by the fast 30-min watchlist scan)."""
    # Pull a wide pool of not-yet-ranked jobs, then keep only the most
    # RELEVANT `limit` to spend LLM calls on (skips off-target sales/HR/etc.).
    pool_size = max(limit * 12, 300)
    with session_scope() as db:
        ctx = user_context.build_user_ctx(db, user_id, resume_json, fresher)
        already = db.query(models.Ranking.job_id).filter(models.Ranking.user_id == user_id)
        cands = (
            db.query(models.Job)
            .filter(models.Job.id.notin_(already))
            .filter(models.Job.description != "")
            .order_by(models.Job.discovered_at.desc())
            .limit(pool_size)
            .all()
        )
        rows = [(j.id, j.title, j.description, j.company) for j in cands]

    fresher = ctx.fresher  # preferences may have forced fresher mode
    if watchlist_only:
        prio = {c for c, p in ctx.watchlist.items() if p == "prioritize"}
        rows = [r for r in rows if company_quality.normalize(r[3]) in prio]

    # Per-user pre-filter (before spending any LLM call).
    before = len(rows)
    rows = [
        r
        for r in rows
        if passes_prefilter(ctx.technical, ctx.years, fresher, r[1], r[2], ctx=ctx, company=r[3])
    ]
    dropped = before - len(rows)

    rows.sort(
        key=lambda r: relevance.relevance_score(ctx.terms, ctx.technical, r[1], r[2]),
        reverse=True,
    )
    new_ids = [r[0] for r in rows[:limit]]
    if not new_ids:
        log.info(
            f"No rankable jobs for user {user_id[:8]} "
            f"(fresher={fresher}, years={ctx.years}, pre-filtered {dropped}/{before})"
        )
        return 0

    log.info(f"Ranking {len(new_ids)} jobs for user {user_id[:8]} (fresher={fresher})")
    ranked = 0
    consecutive_failures = 0
    for jid in new_ids:
        try:
            with session_scope() as db:
                job = db.get(models.Job, jid)
                ranking.rank_job_for_user(
                    db, user_id, resume_json, job, fresher=fresher, ctx=ctx
                )
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


def _do_fetch(run_id: str, log_buf: List[str], company_filter: Optional[set] = None) -> None:
    """Fetch sources → geo gate → ingest into the SHARED pool.

    NOTE: we deliberately DO NOT apply any experience/seniority filter here. The
    shared pool stores ALL valid jobs (every level); fresher/senior fit is decided
    PER USER at ranking time (pipeline.passes_prefilter). This lets an experienced
    user see senior roles while a fresher never does.

    company_filter (watchlist scan): when set, only ingest postings whose company
    matches one of these normalized names — keeps the watchlist scan bounded.
    """
    raws, stats = _fetch_all()
    kept, geo_dropped = geo_filter.filter_rawjobs(raws)
    wl_dropped = 0
    if company_filter:
        before = len(kept)
        kept = [r for r in kept if company_quality.normalize(r.company) in company_filter]
        wl_dropped = before - len(kept)
    with session_scope() as db:
        run = db.get(models.Run, run_id)
        run.jobs_found = len(raws)
        new_jobs, _ = upsert_jobs(db, kept)
        run.jobs_new = len(new_jobs)
        # Attribute new jobs back to their source for health reporting.
        for j in new_jobs:
            if j.source in stats:
                stats[j.source]["added"] += 1
        log_buf.append(
            f"fetched={len(raws)} kept={len(kept)} geo_dropped={geo_dropped} "
            f"watchlist_dropped={wl_dropped} new={len(new_jobs)}"
        )
    try:
        source_health.record(stats)
    except Exception as e:
        log.warning(f"Source-health recording failed: {e}")


def _prioritized_watchlist_norms(user_id: Optional[str]) -> set:
    """Union of prioritized watchlist company-norms across target users."""
    with session_scope() as db:
        q = db.query(models.WatchlistCompany.company_norm).filter(
            models.WatchlistCompany.priority == "prioritize"
        )
        if user_id:
            q = q.filter(models.WatchlistCompany.user_id == user_id)
        return {r[0] for r in q.distinct().all()}


def run_pipeline(
    trigger: str = "manual", user_id: Optional[str] = None, scan_mode: str = "broad"
) -> str:
    """Returns the Run id (or '' if skipped because the user already has a run).

    scan_mode:
      • "broad"     — fetch all sources (if due) + rank everything (default).
      • "watchlist" — NO fetch; rank only the user's prioritised-company jobs.
        Cheap enough to run every ~30 min for near-real-time alerts.
    """
    if user_id:
        with _running_lock:
            if user_id in _running_users:
                log.info(f"User {user_id[:8]} already has a run in progress; skipping.")
                return ""
            _running_users.add(user_id)
    try:
        return _run_pipeline(trigger, user_id, scan_mode)
    finally:
        if user_id:
            with _running_lock:
                _running_users.discard(user_id)


def _run_pipeline(trigger: str, user_id: Optional[str], scan_mode: str = "broad") -> str:
    watchlist_only = scan_mode == "watchlist"
    with session_scope() as db:
        run = models.Run(trigger=trigger, status="running")
        db.add(run)
        db.flush()
        run_id = run.id
        log.info(f"Run {run_id} started ({trigger}, user={user_id or 'ALL'})")

    log_buf: List[str] = []

    # ── 1. fetch ──
    # • broad scan: full fetch (scheduler always; user trigger only if pool stale).
    # • watchlist scan: fetch fresh jobs but ingest ONLY prioritised-company
    #   postings (bounded) so alerts catch brand-new watchlist roles fast.
    fetched = False
    if watchlist_only:
        watch_norms = (
            _prioritized_watchlist_norms(user_id) if settings.watchlist_fetch_enabled else set()
        )
        if watch_norms and _FETCH_LOCK.acquire(blocking=False):
            try:
                _do_fetch(run_id, log_buf, company_filter=watch_norms)
                fetched = True
            finally:
                _FETCH_LOCK.release()
        else:
            log_buf.append(
                "watchlist fetch skipped (no watchlist companies / fetch busy / disabled)"
            )
    else:
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
        n = rank_jobs_for_user(
            uid,
            resume_json,
            settings.max_ranks_per_user,
            fresher=fresher,
            watchlist_only=watchlist_only,
        )
        total_ranked += n
        if n:
            users_ranked += 1
        # Fire alerts for brand-new excellent matches (no-op if not configured).
        try:
            alerts.maybe_alert_user(uid)
        except Exception as e:
            log.warning(f"Alert check failed for {uid[:8]}: {e}")

    # ── 2b. cleanup (only on a BROAD fetch — keep watchlist scans cheap) ──
    pruned = prune_old_jobs(settings.job_retention_days) if (fetched and not watchlist_only) else 0
    if pruned:
        log.info(f"Pruned {pruned} old jobs (>{settings.job_retention_days}d, unused)")
    if fetched and not watchlist_only:
        try:
            with session_scope() as db:
                guest.cleanup_expired(db)
        except Exception as e:
            log.warning(f"Guest cleanup failed: {e}")
        # Closed-job detection (bounded) — flips dead postings to 'closed'.
        try:
            job_checker.run_check()
        except Exception as e:
            log.warning(f"Closed-job check failed: {e}")

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
