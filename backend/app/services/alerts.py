"""
Per-user job alerts (email).

Two flows:
  • Instant alert  — after a run, if the user enabled it and we found brand-new
    EXCELLENT matches since their last alert, email them right away (throttled).
  • Daily digest   — top fresh matches in the last 24h (called by a cron command).

Provider is pluggable via EMAIL_PROVIDER (resend|brevo). If it's unset or the
key is missing, every function is a safe no-op — nothing breaks. We never block
the pipeline on email; failures are logged and swallowed.
"""

from __future__ import annotations

import datetime as dt
from typing import List, Optional

import httpx

from app.config import settings
from app.db import models
from app.db.session import session_scope
from app.utils.logger import log


# ── email transport ──────────────────────────────────────────────────
def email_enabled() -> bool:
    p = (settings.email_provider or "").lower()
    if p == "resend":
        return bool(settings.resend_api_key and settings.email_from)
    if p == "brevo":
        return bool(settings.brevo_api_key and settings.email_from)
    return False


def _send_email(to: str, subject: str, html: str) -> bool:
    """Returns True on success. Safe no-op (False) if provider not configured."""
    if not email_enabled() or not to:
        return False
    provider = settings.email_provider.lower()
    try:
        if provider == "resend":
            r = httpx.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {settings.resend_api_key}"},
                json={"from": settings.email_from, "to": [to], "subject": subject, "html": html},
                timeout=20,
            )
            r.raise_for_status()
            return True
        if provider == "brevo":
            # Brevo expects {name,email}; accept "Name <email>" or bare email.
            sender = settings.email_from
            name, addr = ("AI Job Agent", sender)
            if "<" in sender and ">" in sender:
                name = sender.split("<")[0].strip() or name
                addr = sender.split("<")[1].split(">")[0].strip()
            r = httpx.post(
                "https://api.brevo.com/v3/smtp/email",
                headers={"api-key": settings.brevo_api_key, "content-type": "application/json"},
                json={
                    "sender": {"name": name, "email": addr},
                    "to": [{"email": to}],
                    "subject": subject,
                    "htmlContent": html,
                },
                timeout=20,
            )
            r.raise_for_status()
            return True
    except Exception as e:  # noqa: BLE001
        log.warning(f"Alert email send failed ({provider}): {e}")
    return False


def send_email(to: str, subject: str, html: str) -> bool:
    """Public transactional-email helper (reused by OTP / verification).
    Returns True on success; safe no-op (False) when no provider is configured."""
    return _send_email(to, subject, html)


# ── html rendering ───────────────────────────────────────────────────
def _job_row(job: models.Job, rk: models.Ranking) -> str:
    sig = rk.match_signals or {}
    matched = ", ".join((sig.get("matched_skills") or [])[:6])
    return (
        f'<tr><td style="padding:8px 0;border-bottom:1px solid #eee">'
        f'<a href="{job.url}" style="font-weight:600;color:#2563eb;text-decoration:none">{job.title}</a>'
        f'<div style="color:#555;font-size:13px">{job.company} · {job.location or "—"} · '
        f'<b>{rk.rank_score}</b> {(rk.match_label or "").replace("_"," ")}</div>'
        + (f'<div style="color:#888;font-size:12px">matches: {matched}</div>' if matched else "")
        + "</td></tr>"
    )


def _render(title: str, intro: str, pairs: List[tuple]) -> str:
    rows = "".join(_job_row(j, rk) for j, rk in pairs)
    cta = settings.frontend_url.rstrip("/") + "/jobs"
    return (
        f'<div style="font-family:system-ui,Segoe UI,Arial,sans-serif;max-width:600px;margin:auto">'
        f'<h2 style="color:#111">{title}</h2>'
        f'<p style="color:#444">{intro}</p>'
        f'<table style="width:100%;border-collapse:collapse">{rows}</table>'
        f'<p style="margin-top:20px"><a href="{cta}" '
        f'style="background:#2563eb;color:#fff;padding:10px 18px;border-radius:8px;'
        f'text-decoration:none">Review your shortlist →</a></p>'
        f'<p style="color:#999;font-size:12px;margin-top:24px">You can turn alerts off in '
        f'Settings → Preferences.</p></div>'
    )


# ── flows ────────────────────────────────────────────────────────────
def maybe_alert_user(user_id: str) -> int:
    """Instant alert for new EXCELLENT matches since the user's last alert.
    Returns the number of jobs alerted (0 if disabled/none/not configured)."""
    if not email_enabled():
        return 0
    now = dt.datetime.utcnow()
    with session_scope() as db:
        prefs = db.get(models.UserPreferences, user_id)
        if not prefs or not prefs.alert_instant:
            return 0
        if prefs.last_alert_at:
            mins = (now - prefs.last_alert_at).total_seconds() / 60
            if mins < settings.alert_min_interval_minutes:
                return 0
        user = db.get(models.User, user_id)
        if not user or not user.is_active:
            return 0

        since = prefs.last_alert_at or (now - dt.timedelta(days=1))
        pairs = (
            db.query(models.Job, models.Ranking)
            .join(models.Ranking, models.Ranking.job_id == models.Job.id)
            .filter(
                models.Ranking.user_id == user_id,
                models.Ranking.hidden.is_(False),
                models.Ranking.rank_score >= settings.alert_min_score,
                models.Ranking.created_at >= since,
                models.Ranking.status == "ranked",
            )
            .order_by(models.Ranking.rank_score.desc())
            .limit(10)
            .all()
        )
        if not pairs:
            return 0
        html = _render(
            f"{len(pairs)} excellent job match{'es' if len(pairs) > 1 else ''} for you",
            "We just found roles that strongly fit your profile. Don't miss them:",
            pairs,
        )
        ok = _send_email(user.email, f"🎯 {len(pairs)} new excellent job match(es)", html)
        if ok:
            prefs.last_alert_at = now
            log.info(f"Instant alert sent to {user.email} ({len(pairs)} jobs)")
            return len(pairs)
        return 0


def send_daily_digest(user_id: Optional[str] = None) -> int:
    """Daily digest of the top fresh matches in the last 24h. Returns emails sent."""
    if not email_enabled():
        return 0
    now = dt.datetime.utcnow()
    since = now - dt.timedelta(hours=24)
    sent = 0
    with session_scope() as db:
        q = db.query(models.User).filter(models.User.is_active.is_(True))
        if user_id:
            q = q.filter(models.User.id == user_id)
        for user in q.all():
            prefs = db.get(models.UserPreferences, user.id)
            if not prefs or not prefs.alert_daily_digest:
                continue
            pairs = (
                db.query(models.Job, models.Ranking)
                .join(models.Ranking, models.Ranking.job_id == models.Job.id)
                .filter(
                    models.Ranking.user_id == user.id,
                    models.Ranking.hidden.is_(False),
                    models.Ranking.rank_score >= 65,
                    models.Ranking.created_at >= since,
                )
                .order_by(models.Ranking.rank_score.desc())
                .limit(10)
                .all()
            )
            if not pairs:
                continue
            html = _render(
                f"Your daily job digest — {len(pairs)} fresh match(es)",
                "Here are today's best new roles for your profile:",
                pairs,
            )
            if _send_email(user.email, f"📬 Daily job digest ({len(pairs)})", html):
                sent += 1
    log.info(f"Daily digest: {sent} email(s) sent")
    return sent
