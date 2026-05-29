"""
SQLAlchemy ORM models.

Five entities:
- Job            : a posting we discovered
- Application    : an attempt to apply to a Job
- ResumeVersion  : a tailored resume PDF stored on disk
- CoverLetter    : a generated cover letter
- Run            : one scheduler/manual pipeline execution
- SettingKV      : free-form runtime tweakables editable from the dashboard
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


# ─── Job ─────────────────────────────────────────────────────────────
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

    # AI ranking output
    rank_score: Mapped[Optional[int]] = mapped_column(Integer)
    rank_breakdown: Mapped[Optional[dict]] = mapped_column(JSON)
    rank_reasoning: Mapped[Optional[str]] = mapped_column(Text)
    ats_keywords: Mapped[Optional[list]] = mapped_column(JSON)

    # Bookkeeping
    status: Mapped[str] = mapped_column(String(32), default="new")  # new|ranked|tailored|applied|skipped|failed
    # False for sources behind anti-bot/login walls (LinkedIn, Naukri): we
    # rank + tailor them but never auto-submit — the user applies manually.
    auto_apply: Mapped[bool] = mapped_column(Boolean, default=True)
    # Set when the user clicks "Mark as applied" on a rank-only job.
    applied_manually_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime)
    raw: Mapped[Optional[dict]] = mapped_column(JSON)

    applications: Mapped[list["Application"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


# ─── Application ─────────────────────────────────────────────────────
class Application(Base):
    __tablename__ = "applications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
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
    # True for rank-only jobs the user applies to by hand (LinkedIn/Naukri).
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


# ─── ResumeVersion ───────────────────────────────────────────────────
class ResumeVersion(Base):
    __tablename__ = "resume_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
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
