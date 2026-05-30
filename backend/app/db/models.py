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

    # ranked | tailored | applied | skipped
    status: Mapped[str] = mapped_column(String(32), default="ranked")
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
