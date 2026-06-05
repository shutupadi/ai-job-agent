"""Pydantic schemas for request/response payloads."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, computed_field

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
    match_label: Optional[str] = None
    match_signals: Optional[dict] = None
    apply_type: str = "external"
    source_confidence: str = "unknown"  # high | medium | low | unknown
    open_status: str = "open"           # open | closed | unknown
    company_tier: Optional[int] = None
    watchlisted: bool = False
    saved: bool = False
    hidden: bool = False
    status: str
    auto_apply: bool = True
    applied_manually_at: Optional[dt.datetime] = None


class JobListOut(BaseModel):
    items: List[JobOut]
    total: int


class MarkAppliedRequest(BaseModel):
    note: Optional[str] = None
    applied_at: Optional[dt.datetime] = None


class RerankResponse(BaseModel):
    status: str          # "started" | "reset"
    cleared: int = 0     # how many ranking rows were removed


class FeedbackRequest(BaseModel):
    # save | unsave | not_relevant | more_like_this | hide_company
    action: str = Field(pattern="^(save|unsave|not_relevant|more_like_this|hide_company)$")


# ── User preferences ──
class UserPreferencesOut(BaseModel):
    target_roles: List[str] = []
    experience_level: Optional[str] = None
    min_salary_lpa: Optional[float] = None
    preferred_cities: List[str] = []
    work_modes: List[str] = []
    job_types: List[str] = []
    prioritized_industries: List[str] = []
    blocked_industries: List[str] = []
    preferred_countries: List[str] = []
    needs_sponsorship: bool = False
    excluded_keywords: List[str] = []
    must_have_skills: List[str] = []
    nice_to_have_skills: List[str] = []
    alert_instant: bool = False
    alert_daily_digest: bool = True


class UserPreferencesUpdate(BaseModel):
    target_roles: Optional[List[str]] = None
    experience_level: Optional[str] = None
    min_salary_lpa: Optional[float] = None
    preferred_cities: Optional[List[str]] = None
    work_modes: Optional[List[str]] = None
    job_types: Optional[List[str]] = None
    prioritized_industries: Optional[List[str]] = None
    blocked_industries: Optional[List[str]] = None
    preferred_countries: Optional[List[str]] = None
    needs_sponsorship: Optional[bool] = None
    excluded_keywords: Optional[List[str]] = None
    must_have_skills: Optional[List[str]] = None
    nice_to_have_skills: Optional[List[str]] = None
    alert_instant: Optional[bool] = None
    alert_daily_digest: Optional[bool] = None


# ── Career profile (editable subset of the parsed résumé) ──
class CareerProfileOut(BaseModel):
    name: str = ""
    experience_years: int = 0
    seniority: str = ""
    role_direction: str = ""
    current_role: str = ""
    current_company: str = ""
    target_titles: List[str] = []
    target_job_types: List[str] = []
    domains: List[str] = []
    primary_skills: List[str] = []
    summary: str = ""


class CareerProfileUpdate(BaseModel):
    experience_years: Optional[int] = None
    seniority: Optional[str] = None
    role_direction: Optional[str] = None
    current_role: Optional[str] = None
    current_company: Optional[str] = None
    target_titles: Optional[List[str]] = None
    target_job_types: Optional[List[str]] = None
    domains: Optional[List[str]] = None
    primary_skills: Optional[List[str]] = None
    summary: Optional[str] = None


# ── Watchlist ──
class WatchlistOut(BaseModel):
    id: str
    company: str
    priority: str  # prioritize | normal | block


class WatchlistCreate(BaseModel):
    company: str = Field(min_length=1, max_length=200)
    priority: str = Field(default="prioritize", pattern="^(prioritize|normal|block)$")


class WatchlistPatch(BaseModel):
    priority: str = Field(pattern="^(prioritize|normal|block)$")


# ── Source health (admin) ──
class SourceHealthOut(_ORM):
    source: str
    last_run_at: Optional[dt.datetime] = None
    last_success_at: Optional[dt.datetime] = None
    jobs_found: int = 0
    jobs_added: int = 0
    total_runs: int = 0
    failures: int = 0
    last_error: Optional[str] = None


# ── Admin: rich source dashboard ──
class AdminSourceOut(BaseModel):
    name: str
    enabled: bool
    stub: bool = False
    kind: str = "unknown"          # ats | aggregator | discovery
    confidence: str = "unknown"    # high | medium | low
    configured: bool = True        # all required creds present
    missing_credentials: List[str] = []
    last_run_at: Optional[dt.datetime] = None
    last_success_at: Optional[dt.datetime] = None
    jobs_found: int = 0
    jobs_added: int = 0
    failures: int = 0
    last_error: Optional[str] = None


class SystemHealthOut(BaseModel):
    app_env: str
    email_provider: str = ""
    email_from: str = ""
    email_enabled: bool = False
    sender_freemail: bool = False  # EMAIL_FROM is a freemail domain (poor delivery)
    verification_required: bool = False
    verification_active: bool = False
    email_misconfigured: bool = False


# ── Company tier overrides (admin) ──
class CompanyTierOut(BaseModel):
    company: str
    tier: int


class CompanyTierUpsert(BaseModel):
    company: str = Field(min_length=1, max_length=200)
    tier: int = Field(ge=1, le=5)


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


# ── Auth (multi-user) ──
class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    name: Optional[str] = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class GoogleAuthRequest(BaseModel):
    # Google ID token (JWT) from Google Identity Services on the frontend.
    credential: str


class UserOut(BaseModel):
    id: str
    email: str
    name: Optional[str] = None
    avatar_url: Optional[str] = None
    is_admin: bool = False
    has_resume: bool = False
    email_verified: bool = True
    experience_pref: str = "fresher"  # 'fresher' (entry-only) | 'all'


# ── Email verification (OTP) onboarding ──
class SignupStartRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    name: Optional[str] = None
    # Optional token from a guest résumé upload to attach to the new account.
    guest_token: Optional[str] = None


class VerifyEmailRequest(BaseModel):
    email: EmailStr
    code: str = Field(min_length=4, max_length=10)


class ResendOtpRequest(BaseModel):
    email: EmailStr


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    code: str = Field(min_length=4, max_length=10)
    new_password: str = Field(min_length=8, max_length=200)


class AuthStartResponse(BaseModel):
    """Returned by signup-start when verification is required (no token yet)."""
    status: str = "otp_sent"            # otp_sent | verified
    email: str
    verification_required: bool = True
    # Only populated in local dev when no email provider is configured.
    dev_otp: Optional[str] = None


# ── Guest (pre-signup) résumé ──
class GuestJobSample(BaseModel):
    title: str
    company: str
    location: Optional[str] = None
    remote: bool = False
    url: str


class GuestUploadResponse(BaseModel):
    token: str
    profile: "CareerProfileOut"
    sample_matches: List[GuestJobSample] = []


class PreferencesUpdate(BaseModel):
    experience_pref: str = Field(pattern="^(fresher|all)$")


# ── Admin (read-only visibility) ──
class AdminResumeOut(BaseModel):
    id: str
    filename: Optional[str] = None
    is_active: bool = False
    experience_years: Optional[int] = None
    seniority: Optional[str] = None
    role_direction: Optional[str] = None
    n_skills: int = 0
    text_chars: int = 0
    on_disk: bool = False
    created_at: dt.datetime


class AdminUserOut(BaseModel):
    id: str
    email: str
    name: Optional[str] = None
    is_admin: bool = False
    is_active: bool = True
    experience_pref: str = "fresher"
    login_method: str = "-"
    created_at: dt.datetime
    n_resumes: int = 0
    n_ranked: int = 0
    n_shortlisted: int = 0
    n_applied: int = 0
    resumes: List[AdminResumeOut] = []


class AdminStats(BaseModel):
    total_users: int
    active_users: int
    users_with_resume: int
    total_jobs: int
    total_rankings: int
    total_applications: int
    last_run: Optional[RunOut] = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


# ── Résumé upload (multi-user) ──
class MasterResumeOut(BaseModel):
    """The user's active parsed master résumé."""
    id: Optional[str] = None
    filename: Optional[str] = None
    parsed_json: Optional[dict] = None
    created_at: Optional[dt.datetime] = None
    has_resume: bool = False
