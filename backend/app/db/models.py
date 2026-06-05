"""
SQLAlchemy ORM models.

Multi-tenant design:
- User           : an account (email/password and/or Google).
- Resume         : a user's uploaded + AI-parsed master résumé (latest = active).
- Job            : a posting we discovered — SHARED across all users (one pool).
- Ranking        : a user's AI score/shortlist for a Job (per user × job).
- Application    : a user's attempt/record to apply to a Job.
- ResumeVersion  : a tailored résumé PDF for a (user, job).
- CoverLetter    : a generated cover letter for a (user, job).
- Run            : one global fetch+rank pipeline execution.
- SettingKV      : free-form runtime tweakables.

Jobs are fetched ONCE into the shared pool; each user gets their own Ranking
rows (scored against their résumé). This scales far better than duplicating
jobs per user. Per-user state (score, shortlist status, applied) lives on
Ranking/Application — the legacy rank_* columns on Job are unused in multi-user
mode (kept only to avoid a destructive migration).
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> dt.datetime:
    return dt.datetime.utcnow()


# ─── User ────────────────────────────────────────────────────────────
class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    name: Mapped[Optional[str]] = mapped_column(String(255))
    # Null for Google-only accounts (no local password).
    password_hash: Mapped[Optional[str]] = mapped_column(String(255))
    # Google "sub" (stable user id) for accounts linked to Google sign-in.
    google_sub: Mapped[Optional[str]] = mapped_column(String(255), unique=True)
    avatar_url: Mapped[Optional[str]] = mapped_column(String(512))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    # 'fresher' = only entry-level jobs (deterministic filter); 'all' = every
    # level, matched to the user's résumé. Defaults to fresher (protects new
    # grads from senior-role noise; experienced users toggle it off).
    experience_pref: Mapped[str] = mapped_column(String(16), default="fresher")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)

    resumes: Mapped[list["Resume"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


# ─── Resume (per-user master résumé) ─────────────────────────────────
class Resume(Base):
    __tablename__ = "resumes"
    __table_args__ = (Index("ix_resumes_user_active", "user_id", "is_active"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    filename: Mapped[Optional[str]] = mapped_column(String(255))
    raw_text: Mapped[Optional[str]] = mapped_column(Text)        # extracted text
    parsed_json: Mapped[dict] = mapped_column(JSON, nullable=False)  # structured résumé
    pdf_path: Mapped[Optional[str]] = mapped_column(String(512))  # stored original/preview
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)  # latest = active
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)

    user: Mapped["User"] = relationship(back_populates="resumes")


# ─── Job (shared pool) ───────────────────────────────────────────────
class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_job_source_externalid"),
        Index("ix_jobs_url_hash", "url_hash"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    source: Mapped[str] = mapped_column(String(32), nullable=False)        # greenhouse|lever|yc|linkedin|...
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    url_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    company: Mapped[str] = mapped_column(String(255), nullable=False)
    location: Mapped[Optional[str]] = mapped_column(String(255))
    remote: Mapped[bool] = mapped_column(Boolean, default=False)
    department: Mapped[Optional[str]] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    salary_text: Mapped[Optional[str]] = mapped_column(String(255))
    posted_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime)
    discovered_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)

    # Legacy/global ranking columns — UNUSED in multi-user mode (per-user scores
    # live on Ranking). Kept to avoid a destructive migration.
    rank_score: Mapped[Optional[int]] = mapped_column(Integer)
    rank_breakdown: Mapped[Optional[dict]] = mapped_column(JSON)
    rank_reasoning: Mapped[Optional[str]] = mapped_column(Text)
    ats_keywords: Mapped[Optional[list]] = mapped_column(JSON)

    status: Mapped[str] = mapped_column(String(32), default="new")  # discovery status
    auto_apply: Mapped[bool] = mapped_column(Boolean, default=True)
    # direct | external | discovery (how the user applies; see RawJob.apply_type)
    apply_type: Mapped[str] = mapped_column(String(16), default="external")
    applied_manually_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime)
    raw: Mapped[Optional[dict]] = mapped_column(JSON)

    rankings: Mapped[list["Ranking"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    applications: Mapped[list["Application"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


# ─── Ranking (per user × job) ────────────────────────────────────────
class Ranking(Base):
    __tablename__ = "rankings"
    __table_args__ = (
        UniqueConstraint("user_id", "job_id", name="uq_ranking_user_job"),
        Index("ix_rankings_user_score", "user_id", "rank_score"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )

    rank_score: Mapped[Optional[int]] = mapped_column(Integer)
    rank_breakdown: Mapped[Optional[dict]] = mapped_column(JSON)
    rank_reasoning: Mapped[Optional[str]] = mapped_column(Text)
    ats_keywords: Mapped[Optional[list]] = mapped_column(JSON)

    # Hybrid-ranking outputs (deterministic signals merged with the LLM score).
    # match_label: excellent | good | maybe | not_recommended
    match_label: Mapped[Optional[str]] = mapped_column(String(16))
    # match_signals: {role, experience, skills, company, recency, salary_location,
    #                 matched_skills:[], missing_skills:[], company_tier, watchlisted,
    #                 reasons:[]}
    match_signals: Mapped[Optional[dict]] = mapped_column(JSON)

    # ranked | tailored | applied | skipped
    status: Mapped[str] = mapped_column(String(32), default="ranked")
    # Per-user job actions (fast filtering). Feedback events also logged in JobFeedback.
    saved: Mapped[bool] = mapped_column(Boolean, default=False)
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    applied_manually_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    job: Mapped["Job"] = relationship(back_populates="rankings")


# ─── Application ─────────────────────────────────────────────────────
class Application(Base):
    __tablename__ = "applications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    run_id: Mapped[Optional[str]] = mapped_column(ForeignKey("runs.id", ondelete="SET NULL"))
    resume_version_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("resume_versions.id", ondelete="SET NULL")
    )
    cover_letter_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("cover_letters.id", ondelete="SET NULL")
    )

    status: Mapped[str] = mapped_column(String(32), default="queued")
    # queued | awaiting_approval | manual_pending | submitted | failed | interview | rejected | offer
    approval_required: Mapped[bool] = mapped_column(Boolean, default=False)
    manual: Mapped[bool] = mapped_column(Boolean, default=False)
    approved_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime)
    submitted_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime)

    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[Optional[str]] = mapped_column(Text)
    screenshot_path: Mapped[Optional[str]] = mapped_column(String(512))

    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime, default=_now, onupdate=_now
    )

    job: Mapped["Job"] = relationship(back_populates="applications")
    resume_version: Mapped[Optional["ResumeVersion"]] = relationship()
    cover_letter: Mapped[Optional["CoverLetter"]] = relationship()


# ─── ResumeVersion (tailored, per user × job) ────────────────────────
class ResumeVersion(Base):
    __tablename__ = "resume_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    job_id: Mapped[Optional[str]] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    label: Mapped[str] = mapped_column(String(255), default="tailored")
    pdf_path: Mapped[str] = mapped_column(String(512), nullable=False)
    json_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    ats_keywords: Mapped[Optional[list]] = mapped_column(JSON)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)


# ─── CoverLetter ─────────────────────────────────────────────────────
class CoverLetter(Base):
    __tablename__ = "cover_letters"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    job_id: Mapped[Optional[str]] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    text: Mapped[str] = mapped_column(Text, nullable=False)
    pdf_path: Mapped[Optional[str]] = mapped_column(String(512))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)


# ─── Run ─────────────────────────────────────────────────────────────
class Run(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    started_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)
    finished_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime)
    trigger: Mapped[str] = mapped_column(String(32), default="manual")  # manual|cron-morning|cron-evening
    status: Mapped[str] = mapped_column(String(32), default="running")  # running|success|partial|failed

    jobs_found: Mapped[int] = mapped_column(Integer, default=0)
    jobs_new: Mapped[int] = mapped_column(Integer, default=0)
    ranked: Mapped[int] = mapped_column(Integer, default=0)
    tailored: Mapped[int] = mapped_column(Integer, default=0)
    applied: Mapped[int] = mapped_column(Integer, default=0)
    failed_applications: Mapped[int] = mapped_column(Integer, default=0)

    log: Mapped[Optional[str]] = mapped_column(Text)
    summary: Mapped[Optional[str]] = mapped_column(Text)


# ─── SettingKV ───────────────────────────────────────────────────────
class SettingKV(Base):
    __tablename__ = "settings_kv"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[Optional[dict]] = mapped_column(JSON)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


# ─── UserPreferences (one row per user) ──────────────────────────────
class UserPreferences(Base):
    """Structured search preferences used by the ranker + filters. Stored as
    JSON lists for flexibility. One-to-one with User (user_id is the PK)."""

    __tablename__ = "user_preferences"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    target_roles: Mapped[list] = mapped_column(JSON, default=list)
    experience_level: Mapped[Optional[str]] = mapped_column(String(16))  # fresher|1-3|3-5|5-8|8+
    min_salary_lpa: Mapped[Optional[float]] = mapped_column(Float)
    preferred_cities: Mapped[list] = mapped_column(JSON, default=list)
    work_modes: Mapped[list] = mapped_column(JSON, default=list)  # remote|hybrid|onsite
    job_types: Mapped[list] = mapped_column(JSON, default=list)   # full-time|internship|contract
    prioritized_industries: Mapped[list] = mapped_column(JSON, default=list)
    blocked_industries: Mapped[list] = mapped_column(JSON, default=list)
    preferred_countries: Mapped[list] = mapped_column(JSON, default=list)
    needs_sponsorship: Mapped[bool] = mapped_column(Boolean, default=False)
    excluded_keywords: Mapped[list] = mapped_column(JSON, default=list)
    must_have_skills: Mapped[list] = mapped_column(JSON, default=list)
    nice_to_have_skills: Mapped[list] = mapped_column(JSON, default=list)
    # Alerts
    alert_instant: Mapped[bool] = mapped_column(Boolean, default=False)
    alert_daily_digest: Mapped[bool] = mapped_column(Boolean, default=True)
    last_alert_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


# ─── WatchlistCompany (per user × company) ───────────────────────────
class WatchlistCompany(Base):
    __tablename__ = "watchlist_companies"
    __table_args__ = (
        UniqueConstraint("user_id", "company_norm", name="uq_watchlist_user_company"),
        Index("ix_watchlist_user", "user_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    company: Mapped[str] = mapped_column(String(255), nullable=False)   # display
    company_norm: Mapped[str] = mapped_column(String(255), nullable=False)  # lowercased key
    # prioritize | normal | block
    priority: Mapped[str] = mapped_column(String(16), default="prioritize")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)


# ─── JobFeedback (per user × job action; learning + audit log) ────────
class JobFeedback(Base):
    __tablename__ = "job_feedback"
    __table_args__ = (Index("ix_feedback_user", "user_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE")
    )
    # save | unsave | not_relevant | more_like_this | hide_company | applied | interview
    action: Mapped[str] = mapped_column(String(24), nullable=False)
    company_norm: Mapped[Optional[str]] = mapped_column(String(255))  # for hide_company
    terms: Mapped[Optional[list]] = mapped_column(JSON)  # title tokens, for learning
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)


# ─── SourceHealth (per source) ───────────────────────────────────────
class SourceHealth(Base):
    __tablename__ = "source_health"

    source: Mapped[str] = mapped_column(String(40), primary_key=True)
    last_run_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime)
    last_success_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime)
    jobs_found: Mapped[int] = mapped_column(Integer, default=0)       # last run
    jobs_added: Mapped[int] = mapped_column(Integer, default=0)       # last run (new)
    total_runs: Mapped[int] = mapped_column(Integer, default=0)
    failures: Mapped[int] = mapped_column(Integer, default=0)         # cumulative
    last_error: Mapped[Optional[str]] = mapped_column(Text)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


# ─── CompanyTierOverride (admin-editable; static defaults in code) ────
class CompanyTierOverride(Base):
    __tablename__ = "company_tiers"

    company_norm: Mapped[str] = mapped_column(String(255), primary_key=True)
    company: Mapped[str] = mapped_column(String(255), nullable=False)
    tier: Mapped[int] = mapped_column(Integer, nullable=False)  # 1..4, 5 = avoid
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now, onupdate=_now)
