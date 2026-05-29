"""
Daily summary notifier.

If SMTP creds are present, send the latest run summary by email.
Otherwise just log it.
"""

from __future__ import annotations

import smtplib
from email.message import EmailMessage

from app.config import settings
from app.db import models
from app.db.session import session_scope
from app.utils.logger import log


def _format(run: models.Run, top_jobs: list[models.Job]) -> str:
    lines = [
        f"AI Job Agent — Run {run.id[:8]}",
        f"Trigger: {run.trigger}    Status: {run.status}",
        f"Started: {run.started_at}    Finished: {run.finished_at}",
        "",
        f"Jobs found:        {run.jobs_found}",
        f"New jobs:          {run.jobs_new}",
        f"Ranked:            {run.ranked}",
        f"Resumes tailored:  {run.tailored}",
        f"Applications sent: {run.applied}",
        f"Failed:            {run.failed_applications}",
        "",
        "Top jobs this run:",
    ]
    for j in top_jobs:
        lines.append(f"  [{j.rank_score:>3}] {j.company} — {j.title}  {j.url}")
    return "\n".join(lines)


def notify_summary(run_id: str) -> None:
    with session_scope() as db:
        run = db.get(models.Run, run_id)
        if run is None:
            return
        top = (
            db.query(models.Job)
            .order_by(models.Job.rank_score.desc().nullslast())
            .limit(10)
            .all()
        )
        body = _format(run, top)

    log.info("Summary:\n" + body)

    if not (settings.smtp_host and settings.summary_email_to and settings.smtp_from):
        log.info("SMTP not configured; skipping email.")
        return

    msg = EmailMessage()
    msg["From"] = settings.smtp_from
    msg["To"] = settings.summary_email_to
    msg["Subject"] = f"[AI Job Agent] Run summary — {run.applied} applied / {run.failed_applications} failed"
    msg.set_content(body)
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as s:
            s.starttls()
            if settings.smtp_user:
                s.login(settings.smtp_user, settings.smtp_pass)
            s.send_message(msg)
        log.info(f"Emailed summary to {settings.summary_email_to}")
    except Exception as e:
        log.warning(f"SMTP send failed: {e}")
