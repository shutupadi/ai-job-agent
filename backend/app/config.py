"""
Centralised configuration via pydantic-settings.

Every value is read from environment variables (or a `.env` file in dev).
Do NOT hard-code secrets anywhere else in the codebase.

Note on CSV env vars (KEYWORDS, LOCATIONS, GREENHOUSE_BOARDS, LEVER_COMPANIES):
Pydantic v2's BaseSettings tries to `json.loads()` any env var typed as a
list before validators run. That crashes on `KEYWORDS=SDE,Software Engineer`.
To dodge that, we store them as plain `str` fields with the original env-var
name preserved via `Field(alias=...)`, and expose them as `List[str]`
properties. Call sites still see `settings.keywords` returning a list.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# Repo root (one level above backend/) — this is where the canonical .env lives.
# Computing it absolutely means LOCAL runs (CLI tools, alembic, the LinkedIn
# discovery runner) read the same .env regardless of the current directory.
# In Docker this path won't exist (compose injects the .env as env vars), and a
# missing env_file is simply ignored, so this is safe in both environments.
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _csv(value: str | None) -> List[str]:
    if not value:
        return []
    return [v.strip() for v in str(value).split(",") if v.strip()]


class Settings(BaseSettings):
    # ── Core ──
    app_env: str = "dev"
    log_level: str = "INFO"
    tz: str = "Asia/Kolkata"

    # ── DB ──
    database_url: str = "postgresql+psycopg://jobagent:jobagent@db:5432/jobagent"

    # ── LLM routing ──
    # Primary provider used for ranking / tailoring / cover letters.
    # Valid: "gemini" (default, free tier), "groq" (free tier), "claude" (paid).
    llm_provider: str = "gemini"
    # If the primary fails (rate-limit, outage, etc), try this provider once.
    # Set to empty string to disable failover.
    llm_fallback_provider: str = "groq"
    # Generation budget per call (applies to whichever provider runs).
    llm_max_tokens: int = 2048

    # ── Gemini (Google AI Studio) — free at https://aistudio.google.com ──
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"

    # ── Groq — free at https://console.groq.com ──
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"

    # ── Anthropic Claude (optional, paid) ──
    anthropic_api_key: str = ""
    claude_model: str = "claude-sonnet-4-5"
    # Back-compat: still read CLAUDE_MAX_TOKENS if set, but llm_max_tokens
    # is the new canonical knob.
    claude_max_tokens: int = 2048

    # ── AiCredits.in — OpenAI-compatible gateway (paid, INR billing) ──
    # One key → many models (Claude/Gemini/DeepSeek/…) via the OpenAI
    # chat-completions API. Set LLM_PROVIDER=aicredits to make it primary.
    # IMPORTANT: pick a NON-thinking model. Reasoning models (gemini-2.5-flash,
    # which the "gemini-2.0-flash" alias maps to; deepseek-r1; etc.) spend the
    # token budget on hidden reasoning and truncate JSON. anthropic/claude-3-haiku
    # and gemini-2.0-flash-lite are verified-good, cheap, non-thinking choices.
    aicredits_api_key: str = ""
    aicredits_base_url: str = "https://api.aicredits.in/v1"
    aicredits_model: str = "anthropic/claude-3-haiku"

    # ── Candidate identity ──
    candidate_full_name: str = "Candidate"
    candidate_email: str = "candidate@example.com"
    candidate_phone: str = "+91-9000000000"
    candidate_linkedin: str = ""
    candidate_github: str = ""
    candidate_portfolio: str = ""
    candidate_current_location: str = "Noida, India"
    candidate_work_auth: str = "India / open to sponsorship"
    candidate_notice_period: str = "Immediately"
    candidate_expected_ctc_lpa: float = 22.0

    # ── Search prefs (CSV-as-str; expose as List[str] via @property below) ──
    keywords_raw: str = Field(default="Software Engineer", alias="KEYWORDS")
    experience_level: str = "entry"
    locations_raw: str = Field(default="Remote", alias="LOCATIONS")
    include_remote: bool = True
    include_international: bool = True
    min_salary_lpa: float = 18.0

    # ── Geo filter ──
    # When True, the pipeline only keeps jobs that are (a) in India, (b) remote
    # (if include_remote), or (c) international roles that mention visa
    # sponsorship (if include_international). Everything else is dropped before
    # it ever hits the DB or the LLM ranker — saves quota and noise.
    geo_filter_enabled: bool = True

    # ── Experience filter (fresher gate) ──
    # When True, drop roles that aren't fresher/entry-level *before* persisting
    # or ranking: senior/lead/staff/manager titles and roles requiring more than
    # max_experience_years of experience. Entry/new-grad/intern signals and
    # roles that don't state a number are kept. The candidate is a final-year
    # student (~0 yrs professional experience).
    experience_filter_enabled: bool = True
    max_experience_years: int = 2

    # ── Auth (multi-user) ──
    # JWT signing secret — MUST be overridden in production (set JWT_SECRET).
    jwt_secret: str = "dev-insecure-change-me-please-min-32-characters-long"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7  # 7 days
    # Google OAuth (optional) — leave blank to hide the "Sign in with Google"
    # button. Create credentials at https://console.cloud.google.com/apis/credentials
    google_client_id: str = ""
    google_client_secret: str = ""
    # Public URL of the frontend — used for OAuth redirects + email links.
    frontend_url: str = "http://localhost:3000"
    # Max résumé upload size (MB) and how many jobs to rank per user per run.
    max_resume_mb: int = 5
    max_ranks_per_user: int = 30
    # Auto-cleanup: delete jobs older than this many days that nobody applied
    # to / tailored — keeps the shared pool fresh and small. 0 disables.
    job_retention_days: int = 30

    # ── Source toggles ──
    enable_greenhouse: bool = True
    enable_lever: bool = True
    enable_ycombinator: bool = True
    enable_workday: bool = False
    enable_oracle: bool = False
    enable_linkedin: bool = False
    enable_indeed: bool = False
    enable_naukri: bool = False
    enable_wellfound: bool = False

    greenhouse_boards_raw: str = Field(default="", alias="GREENHOUSE_BOARDS")
    lever_companies_raw: str = Field(default="", alias="LEVER_COMPANIES")
    # Workday career sites. CSV of "host|tenant|site" triples, e.g.
    #   nvidia.wd5.myworkdayjobs.com|nvidia|NVIDIAExternalCareerSite
    # (comma-separated for multiple companies).
    workday_tenants_raw: str = Field(default="", alias="WORKDAY_TENANTS")
    # Oracle Recruiting Cloud (Candidate Experience) career sites. Many banks &
    # enterprises run on this (e.g. JPMorgan Chase). CSV of "host|siteNumber"
    # pairs (optionally a 3rd "|Display Name"), e.g.
    #   jpmc.fa.oraclecloud.com|CX_1001|JPMorgan Chase
    oracle_tenants_raw: str = Field(default="", alias="ORACLE_TENANTS")
    yc_query: str = "software engineer"

    # ── Best-effort rank-only source volume caps ──
    # LinkedIn & Naukri are scraped from their *public* listing pages (no login)
    # purely to RANK jobs — never to auto-apply. Keep volumes low and polite:
    # high volume gets your IP rate-limited/blocked and violates their ToS.
    linkedin_max: int = 25
    naukri_max: int = 25
    workday_max_per_tenant: int = 40
    oracle_max_per_tenant: int = 40

    # ── LinkedIn logged-in DISCOVERY (LOCAL, attended) ──
    # Used only by `python -m app.automation.linkedin_discover`, NOT the Docker
    # pipeline. You log in once in a real browser; the session persists in
    # linkedin_profile_dir. The runner scrapes recommended + searched jobs into
    # the DB for ranking — it NEVER applies. Keep volume polite. NOTE: scraping
    # LinkedIn (even logged in, even without applying) is against its User
    # Agreement; this is discovery-only and rate-limited to limit risk.
    linkedin_discover_max: int = 40         # max jobs ingested per local run

    # ── Apply behaviour ──
    apply_mode: str = "auto"  # "auto" | "approval"
    min_rank_to_apply: int = 70
    max_applications_per_run: int = 15
    rate_limit_seconds: int = 45
    headless_browser: bool = True

    # ── LLM budget controls (avoid free-tier daily quota exhaustion) ──
    # Max jobs to rank per pipeline run. With Gemini free tier (~200 RPD) and
    # Groq free tier (~100K TPD), 25 ranks/run × 2 runs/day = 50/day fits
    # comfortably with headroom for retries.
    max_ranks_per_run: int = 25
    # Seconds to sleep between consecutive LLM calls. 4s keeps us under
    # Gemini's 15 RPM free-tier ceiling.
    llm_call_delay_seconds: float = 4.0
    # Stop ranking after this many consecutive LLM failures (likely 429s).
    # Prevents grinding through dozens of doomed calls.
    rank_circuit_breaker: int = 5

    # ── Scheduler ──
    schedule_cron_morning: str = "0 9 * * *"
    schedule_cron_evening: str = "0 19 * * *"

    # ── Notifications ──
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_pass: str = ""
    smtp_from: str = ""
    summary_email_to: str = ""

    # ── Paths ──
    project_root: Path = Path(__file__).resolve().parent.parent
    storage_dir: Path = Path(__file__).resolve().parent.parent / "storage"
    data_dir: Path = Path(__file__).resolve().parent.parent / "data"
    prompts_dir: Path = Path(__file__).resolve().parent.parent / "prompts"
    logs_dir: Path = Path(__file__).resolve().parent.parent / "logs"

    model_config = SettingsConfigDict(
        # Load the repo-root .env (absolute) first, then a local ./.env if present.
        # Real environment variables still take precedence over both (so Docker
        # compose injection and the test conftest overrides win).
        env_file=(str(_REPO_ROOT / ".env"), ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,  # accept both alias (KEYWORDS) and field name
    )

    @field_validator("database_url")
    @classmethod
    def _normalize_db_url(cls, v: str) -> str:
        """Cloud Postgres add-ons (Render/Railway/Heroku) hand out driver-less
        URLs like postgres:// or postgresql://. SQLAlchemy needs the psycopg v3
        driver, so normalise to postgresql+psycopg://. Leaves sqlite and already
        -qualified (postgresql+psycopg://) URLs untouched."""
        if v.startswith("postgres://"):
            return "postgresql+psycopg://" + v[len("postgres://"):]
        if v.startswith("postgresql://"):
            return "postgresql+psycopg://" + v[len("postgresql://"):]
        return v

    # ── List accessors ── (call sites get List[str] as before) ──
    @property
    def keywords(self) -> List[str]:
        return _csv(self.keywords_raw)

    @property
    def locations(self) -> List[str]:
        return _csv(self.locations_raw)

    @property
    def greenhouse_boards(self) -> List[str]:
        return _csv(self.greenhouse_boards_raw)

    @property
    def lever_companies(self) -> List[str]:
        return _csv(self.lever_companies_raw)

    @property
    def workday_tenants(self) -> List[str]:
        """Raw "host|tenant|site" entries; parsed by the Workday source."""
        return _csv(self.workday_tenants_raw)

    @property
    def oracle_tenants(self) -> List[str]:
        """Raw "host|siteNumber[|Display]" entries; parsed by the Oracle source."""
        return _csv(self.oracle_tenants_raw)

    @property
    def linkedin_profile_dir(self) -> Path:
        """Persistent Playwright profile so LinkedIn login survives across runs."""
        return self.storage_dir / "linkedin_profile"

    @property
    def active_llm_model(self) -> str:
        """The model string of the currently-selected primary provider."""
        return {
            "aicredits": self.aicredits_model,
            "gemini": self.gemini_model,
            "groq": self.groq_model,
            "claude": self.claude_model,
        }.get(self.llm_provider.lower(), self.llm_provider)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    s = Settings()
    for p in (s.storage_dir, s.data_dir, s.logs_dir):
        p.mkdir(parents=True, exist_ok=True)
    (s.storage_dir / "resumes").mkdir(parents=True, exist_ok=True)
    (s.storage_dir / "cover_letters").mkdir(parents=True, exist_ok=True)
    (s.storage_dir / "screenshots").mkdir(parents=True, exist_ok=True)
    (s.storage_dir / "exports").mkdir(parents=True, exist_ok=True)
    return s


settings = get_settings()
