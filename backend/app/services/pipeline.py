"""
End-to-end pipeline.

Stages:
  1. fetch     — pull RawJobs from every enabled source.
  1b. geo gate — keep India / remote / sponsored-international only.
  1c. exp gate — keep fresher / entry-level only (drop senior + high-YOE roles).
  2. ingest    — dedupe and persist as Job rows.
  3. rank      — LLM rank every new job, store score + breakdown.
  4. tailor+apply — ONLY in legacy APPLY_MODE=auto. In the default
                    APPLY_MODE=approval the run STOPS after ranking and the
                    shortlist is surfaced for manual review; tailoring happens
                    on demand when the user approves a job in the dashboard.
  5. summarise — write Run summary, optionally email it.

This module is callable from:
  - FastAPI POST /api/runs/trigger
  - APScheduler every 12h
  - CLI: python -m app.scheduler.jobs run-once
"""

from __future__ import annotations

import datetime as dt
import time
import traceback
from typing import List

from sqlalchemy.orm import Session

from app.config import settings
from app.db import models
from app.db.session import session_scope
from app.services import cover_letter as cover_letter_svc
from app.services import experience_filter
from app.services import export as export_svc
from app.services import geo_filter
from app.services import ranking
from app.services import resume_engine
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


def _candidates_for_apply(db: Session, run: models.Run) -> List[models.Job]:
    q = (
        db.query(models.Job)
        .filter(models.Job.status == "ranked")
        .filter(models.Job.rank_score.isnot(None))
        .filter(models.Job.rank_score >= settings.min_rank_to_apply)
        .order_by(models.Job.rank_score.desc())
        .limit(settings.max_applications_per_run)
    )
    return q.all()


def rank_new_jobs(limit: int) -> int:
    """Rank up to `limit` jobs currently in status 'new'.

    Budget-aware, rate-limited, circuit-broken. Returns the count successfully
    ranked. Reused by BOTH the scheduled pipeline and the local LinkedIn
    discovery runner so freshly ingested jobs can be ranked immediately.

    Why each guard exists:
    - limit: respect free-tier daily quotas.
    - sleep(llm_call_delay_seconds): stay under per-minute RPM limits.
    - consecutive-failure circuit breaker: if quotas are blown, don't burn the
      rest of the run on calls that will all 429.
    """
    with session_scope() as db:
        new_ids = [
            j.id
            for j in db.query(models.Job)
            .filter(models.Job.status == "new")
            .order_by(models.Job.discovered_at.desc())
            .limit(limit)
            .all()
        ]
    log.info(
        f"Ranking up to {len(new_ids)} jobs "
        f"(cap={limit}, delay={settings.llm_call_delay_seconds}s)"
    )
    ranked = 0
    consecutive_failures = 0
    for jid in new_ids:
        try:
            with session_scope() as db:
                job = db.get(models.Job, jid)
                ranking.rank_job(db, job)
                ranked += 1
                consecutive_failures = 0
        except Exception as e:
            consecutive_failures += 1
            log.warning(f"Rank failed for {jid} ({consecutive_failures} in a row): {e}")
            if consecutive_failures >= settings.rank_circuit_breaker:
                log.error(
                    f"Circuit breaker tripped after {consecutive_failures} consecutive "
                    "rank failures (likely free-tier quota exhausted). Stopping ranking; "
                    "remaining jobs stay 'new' and are picked up next run."
                )
                break
        # Pace ourselves — even on failure, to avoid hammering rate limits.
        time.sleep(settings.llm_call_delay_seconds)
    return ranked


def _auto_tailor_and_apply(run_id: str) -> tuple[int, int, int, int]:
    """Legacy auto-apply stage (APPLY_MODE=auto). Returns
    (tailored, applied, failed, manual_pending)."""
    tailored = applied = failed = manual_pending = 0
    with session_scope() as db:
        candidate_ids = [j.id for j in _candidates_for_apply(db, db.get(models.Run, run_id))]

    from app.automation.apply import apply_to_job  # lazy: keep optional dep light

    for jid in candidate_ids:
        try:
            with session_scope() as db:
                job = db.get(models.Job, jid)
                auto = bool(job.auto_apply)
                label = f"{job.company} – {job.title}"
                rv = resume_engine.tailor_for_job(db, job)
                cl = cover_letter_svc.generate_for_job(db, job, rv.json_payload)
                rv_id, cl_id = rv.id, cl.id
                job.status = "tailored"
                tailored += 1
                app_row = models.Application(
                    job_id=job.id,
                    run_id=run_id,
                    resume_version_id=rv.id,
                    cover_letter_id=cl.id,
                    status="manual_pending" if not auto else "queued",
                    approval_required=(settings.apply_mode.lower() == "approval"),
                    manual=(not auto),
                    attempts=0 if not auto else 1,
                )
                db.add(app_row)
                db.flush()
                app_id = app_row.id

            if not auto:
                manual_pending += 1
                log.info(f"Rank-only [{label}] tailored → manual apply queued")
                continue

            result = apply_to_job(
                job=_load_job_snapshot(jid),
                resume_version=_load_resume_snapshot(rv_id),
                cover_letter=_load_cover_snapshot(cl_id),
            )

            with session_scope() as db:
                app_row = db.get(models.Application, app_id)
                job = db.get(models.Job, jid)
                if result.awaiting_approval:
                    app_row.status = "awaiting_approval"
                    app_row.screenshot_path = result.screenshot_path
                    job.status = "tailored"
                elif result.success:
                    app_row.status = "submitted"
                    app_row.submitted_at = dt.datetime.utcnow()
                    app_row.screenshot_path = result.screenshot_path
                    job.status = "applied"
                    applied += 1
                else:
                    app_row.status = "failed"
                    app_row.error = result.error
                    app_row.screenshot_path = result.screenshot_path
                    job.status = "failed"
                    failed += 1

            time.sleep(settings.rate_limit_seconds)
        except Exception as e:
            failed += 1
            tb = traceback.format_exc(limit=2)
            log.error(f"Tailor/apply failed for {jid}: {e}\n{tb}")
            with session_scope() as db:
                job = db.get(models.Job, jid)
                if job:
                    job.status = "failed"
    return tailored, applied, failed, manual_pending


def run_pipeline(trigger: str = "manual") -> str:
    """Returns the Run id."""
    with session_scope() as db:
        run = models.Run(trigger=trigger, status="running")
        db.add(run)
        db.flush()
        run_id = run.id
        log.info(f"Run {run_id} started ({trigger})")

    log_buf: List[str] = []

    # ── 1. fetch ──
    raws = _fetch_all()
    # ── 1b. location gate: keep India / remote / sponsored-international only ──
    kept, geo_dropped = geo_filter.filter_rawjobs(raws)
    if geo_dropped:
        log.info(
            f"Geo filter: kept {len(kept)}, dropped {geo_dropped} "
            "(outside India / not remote / no sponsorship)"
        )
    # ── 1c. experience gate: keep fresher / entry-level only ──
    kept, exp_dropped = experience_filter.filter_rawjobs(kept)
    if exp_dropped:
        log.info(
            f"Experience filter: kept {len(kept)}, dropped {exp_dropped} "
            "(senior / requires prior experience)"
        )

    with session_scope() as db:
        run = db.get(models.Run, run_id)
        run.jobs_found = len(raws)
        # ── 2. ingest ──
        new_jobs, _ = upsert_jobs(db, kept)
        run.jobs_new = len(new_jobs)
        log_buf.append(
            f"fetched={len(raws)} kept={len(kept)} "
            f"geo_dropped={geo_dropped} exp_dropped={exp_dropped} new={len(new_jobs)}"
        )

    # ── 3. rank ──
    ranked = rank_new_jobs(settings.max_ranks_per_run)
    with session_scope() as db:
        run = db.get(models.Run, run_id)
        run.ranked = ranked
        log_buf.append(f"ranked={ranked}")

    # ── 4. tailor + apply — ONLY in legacy auto mode ──
    tailored = applied = failed = manual_pending = 0
    if settings.apply_mode.lower() == "auto":
        tailored, applied, failed, manual_pending = _auto_tailor_and_apply(run_id)
    else:
        log.info(
            "approval mode: ranking only — shortlist surfaced for manual review "
            "(no auto-tailor, no auto-apply). Tailor on demand from the dashboard."
        )

    # ── 5. finalise ──
    with session_scope() as db:
        run = db.get(models.Run, run_id)
        run.tailored = tailored
        run.applied = applied
        run.failed_applications = failed
        run.finished_at = dt.datetime.utcnow()
        run.status = "success" if failed == 0 else "partial"
        log_buf.append(f"manual_pending={manual_pending}")
        run.log = "\n".join(log_buf)

        # How many ranked jobs clear the shortlist threshold (for the summary).
        shortlist_count = (
            db.query(models.Job)
            .filter(models.Job.status.in_(("ranked", "tailored")))
            .filter(models.Job.rank_score >= settings.min_rank_to_apply)
            .count()
        )

        # Write today's shortlist worklist (jobs the user reviews + applies by hand).
        try:
            export_path, export_count = export_svc.write_daily_export(db)
        except Exception as e:
            log.warning(f"Shortlist export failed: {e}")
            export_path, export_count = None, 0

        mode = settings.apply_mode.lower()
        summary = (
            f"Run {run_id[:8]} ({trigger}) [{mode} mode]\n"
            f"  jobs found:        {run.jobs_found}\n"
            f"  new jobs:          {run.jobs_new}\n"
            f"  ranked:            {run.ranked}\n"
            f"  shortlist (>= {settings.min_rank_to_apply}): {shortlist_count}\n"
        )
        if mode == "auto":
            summary += (
                f"  tailored:          {run.tailored}\n"
                f"  applied (auto):    {run.applied}\n"
                f"  manual to apply:   {manual_pending}\n"
                f"  failed:            {run.failed_applications}\n"
            )
        summary += (
            f"  shortlist worklist: {export_count} jobs"
            + (f" → {export_path}" if export_path else "")
            + "\n"
        )
        run.summary = summary
        log.info(summary)

    try:
        notify_summary(run_id)
    except Exception as e:
        log.warning(f"Notification failed: {e}")

    return run_id


# ── tiny snapshot helpers so we can drop the session before Playwright ──
def _load_job_snapshot(jid: str) -> models.Job:
    with session_scope() as db:
        j = db.get(models.Job, jid)
        db.expunge(j)
        return j


def _load_resume_snapshot(rid: str) -> models.ResumeVersion:
    with session_scope() as db:
        r = db.get(models.ResumeVersion, rid)
        db.expunge(r)
        return r


def _load_cover_snapshot(cid: str) -> models.CoverLetter:
    with session_scope() as db:
        c = db.get(models.CoverLetter, cid)
        db.expunge(c)
        return c
