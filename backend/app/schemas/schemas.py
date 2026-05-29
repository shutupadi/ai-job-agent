"""Pydantic schemas for request/response payloads."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.config import settings


class _ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


def _files_url(pdf_path: Optional[str]) -> Optional[str]:
    """Map an on-disk storage path to its public /files/... URL.

    main.py mounts StaticFiles(storage_dir) at /files, so a resume at
    <storage>/resumes/foo.pdf is served at /files/resumes/foo.pdf. The frontend
    prefixes this with the API base to build a working download link."""
    if not pdf_path:
        return None
    try:
        rel = Path(pdf_path).resolve().relative_to(Path(settings.storage_dir).resolve())
        return "/files/" + str(rel).replace("\\", "/")
    except Exception:
        return None


# ── Jobs ──
class JobOut(_ORM):
    id: str
    source: str
    external_id: str
    url: str
    title: str
    company: str
    location: Optional[str] = None
    remote: bool = False
    department: Optional[str] = None
    description: str = ""
    salary_text: Optional[str] = None
    posted_at: Optional[dt.datetime] = None
    discovered_at: dt.datetime
    rank_score: Optional[int] = None
    rank_breakdown: Optional[dict] = None
    rank_reasoning: Optional[str] = None
    ats_keywords: Optional[List[str]] = None
    status: str
    auto_apply: bool = True
    applied_manually_at: Optional[dt.datetime] = None


class JobListOut(BaseModel):
    items: List[JobOut]
    total: int


class MarkAppliedRequest(BaseModel):
    note: Optional[str] = None
    applied_at: Optional[dt.datetime] = None


# ── Applications ──
class ApplicationOut(_ORM):
    id: str
    job_id: str
    run_id: Optional[str] = None
    resume_version_id: Optional[str] = None
    cover_letter_id: Optional[str] = None
    status: str
    approval_required: bool
    manual: bool = False
    approved_at: Optional[dt.datetime] = None
    submitted_at: Optional[dt.datetime] = None
    attempts: int
    error: Optional[str] = None
    screenshot_path: Optional[str] = None
    created_at: dt.datetime
    updated_at: dt.datetime


class ApplicationListOut(BaseModel):
    items: List[ApplicationOut]
    total: int


class ApplicationStatusUpdate(BaseModel):
    status: str = Field(
        ...,
        description="queued|awaiting_approval|manual_pending|submitted|failed|interview|rejected|offer",
    )


# ── Runs ──
class RunOut(_ORM):
    id: str
    started_at: dt.datetime
    finished_at: Optional[dt.datetime] = None
    trigger: str
    status: str
    jobs_found: int
    jobs_new: int
    ranked: int
    tailored: int
    applied: int
    failed_applications: int
    summary: Optional[str] = None


# ── Settings ──
class SettingsOut(BaseModel):
    apply_mode: str
    min_rank_to_apply: int
    max_applications_per_run: int
    rate_limit_seconds: int
    keywords: List[str]
    locations: List[str]
    greenhouse_boards: List[str]
    lever_companies: List[str]
    enable_greenhouse: bool
    enable_lever: bool
    enable_ycombinator: bool
    enable_workday: bool
    enable_oracle: bool
    enable_linkedin: bool
    enable_naukri: bool
    include_remote: bool
    include_international: bool
    geo_filter_enabled: bool
    experience_filter_enabled: bool
    max_experience_years: int
    llm_provider: str
    llm_model: str


class SettingsPatch(BaseModel):
    apply_mode: Optional[str] = None
    min_rank_to_apply: Optional[int] = None
    max_applications_per_run: Optional[int] = None
    rate_limit_seconds: Optional[int] = None


# ── Dashboard summary ──
class DashboardSummary(BaseModel):
    total_jobs: int
    # Review-workflow metrics (approval mode):
    ranked: int = 0
    shortlisted: int = 0   # ranked/tailored, >= threshold, not yet applied
    tailored: int = 0      # résumé + cover letter prepared
    applied: int = 0       # marked applied (manual) or auto-submitted
    apply_mode: str = "approval"
    min_rank_to_apply: int = 70
    llm_model: str = ""
    # Application pipeline counts (still meaningful for tracking outcomes):
    total_applications: int
    submitted: int
    failed: int
    awaiting_approval: int
    interviews: int
    rejected: int
    last_run: Optional[RunOut] = None
    top_jobs: List[JobOut] = []


# ── Resume ──
class ResumeVersionOut(_ORM):
    id: str
    job_id: Optional[str] = None
    label: str
    pdf_path: str
    ats_keywords: Optional[List[str]] = None
    created_at: dt.datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def download_url(self) -> Optional[str]:
        return _files_url(self.pdf_path)


class CoverLetterOut(_ORM):
    id: str
    job_id: Optional[str] = None
    pdf_path: Optional[str] = None
    created_at: dt.datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def download_url(self) -> Optional[str]:
        return _files_url(self.pdf_path)


class TailorRequest(BaseModel):
    job_id: str


class TailorResponse(BaseModel):
    """Returned by POST /api/resume/tailor and GET /api/resume/for-job/{id}."""
    resume: Optional[ResumeVersionOut] = None
    cover_letter: Optional[CoverLetterOut] = None
