# AI Job Agent

<!-- Replace `shutupadi/ai-job-agent` below with your actual GitHub owner/repo. -->
[![CI](https://github.com/shutupadi/ai-job-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/shutupadi/ai-job-agent/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/shutupadi/ai-job-agent/branch/main/graph/badge.svg)](https://codecov.io/gh/shutupadi/ai-job-agent)
![Python](https://img.shields.io/badge/python-3.11-blue)
![Next.js](https://img.shields.io/badge/Next.js-14-black)
![License](https://img.shields.io/badge/license-MIT-green)

An end-to-end, AI-powered job-search assistant for a **fresher / new-grad**.
It aggregates postings from many sources, **filters to entry-level roles only**,
ranks them with an LLM, and surfaces a **shortlist for you to review**. When you
approve a job, it tailors your résumé + a cover letter for that posting (factually
grounded, no fabrication) and gives you the PDFs to apply with. Runs every 12h.

> **Workflow philosophy:** accuracy over volume, and **human-in-the-loop**. By
> default (`APPLY_MODE=approval`) the pipeline **never auto-submits** — it ranks
> and shortlists; you review, tailor, and apply yourself. A legacy `auto` mode
> still exists for ATS portals if you want it.

## Architecture

```
┌──────────────┐    ┌───────────────┐    ┌────────────────┐
│ Next.js UI   │───▶│ FastAPI API   │───▶│ PostgreSQL DB  │
│ (review +    │    │ (Python 3.11) │    │                │
│  tailoring)  │    └──────┬────────┘    └────────────────┘
└──────────────┘           │
        ┌──────────┬───────┴────┬───────────────┬───────────────┐
        ▼          ▼            ▼               ▼               ▼
  ┌──────────┐ ┌────────┐  ┌──────────┐   ┌──────────┐   ┌──────────┐
  │ Sources  │ │ Geo +  │  │  LLM     │   │ Résumé / │   │ Notifier │
  │ adapters │ │ fresher│  │ (rank /  │   │ cover    │   │ (email   │
  │ GH/Lever/│ │ filters│  │ tailor / │   │ letter   │   │ summary) │
  │ YC/WD/   │ │        │  │ CL)      │   │ PDF gen  │   │          │
  │ Oracle/  │ └────────┘  └──────────┘   └──────────┘   └──────────┘
  │ LinkedIn │       ▲
  └──────────┘       │ APScheduler (every 12h: 09:00 + 21:00 IST)
```

## Features

1. **Multi-source aggregation** — Greenhouse, Lever, YC, **Workday** (CXS API,
   e.g. Morgan Stanley), **Oracle Recruiting Cloud** (e.g. JPMorgan Chase), plus
   LinkedIn (public listings) and Naukri.
2. **Geo gate** — keep only India / remote / international-with-sponsorship roles.
3. **Fresher gate** — drop senior/lead/staff/manager titles and roles requiring
   more than `MAX_EXPERIENCE_YEARS` (default 2), *before* ranking. This is the
   core "stop showing me jobs that need experience" filter.
4. **AI ranking** — each surviving job scored 0–100 (salary, company quality, ATS
   match, growth, remote, shortlist-likelihood). The LLM is told the candidate is
   a fresher and caps senior/high-YOE roles.
5. **Review shortlist** — the dashboard shows entry-level matches ≥ threshold,
   sorted by score. Nothing is applied automatically.
6. **On-demand tailoring** — click **Tailor & prepare** on a job → a JD-specific
   résumé + cover letter are generated and offered as **downloads**. Edits stay
   factually grounded in your master résumé (identity fields are force-locked).
7. **LinkedIn logged-in discovery** — an optional local runner scrapes your
   Recommended + searched jobs into the DB for ranking (it **never applies**).
8. **Scheduler** — full pipeline every 12h. **Notifier** — optional email summary.
9. **Safety** — rate limits, captcha/wall detection, secrets via env only, no
   fabrication in résumés.

## Job-intelligence layer (v2)

Built for **quality over quantity** — a smaller set of genuinely excellent,
explained matches rather than a flood of postings:

- **Career profile** — the parsed résumé is upgraded into a structured, **editable**
  profile (experience, seniority, role direction, target titles, domains, skills).
  Edit it in **Preferences** so ranking uses corrected values, not raw AI guesses.
- **Preferences** — target roles, min salary, cities, work mode, job types,
  must-have / nice-to-have skills, blocked industries, excluded keywords, visa
  needs, and alert settings. All feed the ranker.
- **Company watchlist** — prioritise / block companies per user. Prioritised
  companies are scanned more often and **boosted (only when role fit is good)**.
- **Company-quality tiers** (1–4, plus an "avoid" tier for spam/consultancy/scam
  postings) used as a ranking signal — never a substitute for role fit. Admin
  overridable.
- **Hybrid explainable ranking** — deterministic signals fused with the LLM:
  role 30% · experience 25% · skills 20% · company/watchlist 10% · recency 10% ·
  salary/location 5%. Each job shows a **match label** (Excellent / Good / Maybe /
  Not recommended), **matched & missing skills**, and **why it's shown**.
  Hard rules drop wrong-profession, wrong-level, blocked, and scam postings.
- **Feedback learning** — Save · More like this · Not relevant · Hide company.
  Choices reshape that user's future rankings (and persist across re-ranks).
- **Re-rank / reset** — re-score from the shared pool against your latest résumé +
  preferences; saved / tailored / applied jobs are always preserved.
- **Alerts** — instant email for excellent matches + a daily digest (Resend or
  Brevo; safe no-op until configured). A fast **watchlist scan** (every ~30 min via
  the scheduler) powers near-real-time alerts; broad scans run every 6–12h.
- **More sources** — added **Ashby** and **SmartRecruiters** public-API adapters
  (config-driven, fail-graceful). Every source records **health** (last run, found,
  added, failures, last error) visible in the admin dashboard. Jobs are tagged
  `direct` / `external` / `discovery`.
- **Admin** — `/admin` shows users, résumé parse quality, runs, and source health.
  Grant access via `ADMIN_EMAILS`.

## Onboarding & email verification (v3)

A try-before-you-signup flow plus OTP-verified accounts:

- **Guest résumé upload** — the landing page (`/`, no login) lets a visitor upload
  a PDF/DOCX/TXT résumé. It's parsed with the same engine and shown as a preview:
  career profile, experience level, target roles, primary skills, and a free
  **sample-matches** teaser (deterministic, no LLM cost). The parse is stored
  against an unguessable token for `GUEST_SESSION_TTL_HOURS` and cleaned up after.
- **Signup → email OTP** — `POST /api/auth/signup-start` creates an *unverified*
  account and emails a 6-digit code; `POST /api/auth/verify-email` confirms it and
  logs the user in; `POST /api/auth/resend-otp` resends (throttled, no account
  enumeration). The guest résumé is **attached to the new account** automatically.
  Codes are HMAC-hashed (never stored in plaintext), expire in `OTP_TTL_MINUTES`,
  and lock after `OTP_MAX_ATTEMPTS` wrong tries. The old `/api/auth/signup` route
  still exists and is routed through verification for compatibility.
- **Verified-only features** — `get_verified_user` gates run pipeline, rerank,
  save/feedback, tailor, mark-applied, set alerts, and watchlist edits. Reading
  (dashboard, jobs, profile) stays open to logged-in users.
- **Graceful degradation** — verification is only *enforced* when it can be
  delivered: with an email provider configured (any env) it sends real codes; in
  dev without a provider the code is logged to the console (and returned as
  `dev_otp`); in **prod without a provider** signups auto-verify so the live site
  never bricks. Existing users and Google sign-ins are treated as verified.

## Quick start (Docker)

```bash
cp .env.example .env
# Edit .env. The minimum you need:
#   AICREDITS_API_KEY  — your paid OpenAI-compatible gateway key (primary LLM)
#   GROQ_API_KEY       — free at https://console.groq.com/keys (fallback)
#   CANDIDATE_*        — your name, email, phone, LinkedIn, etc.
docker compose up --build
```

- API:        http://localhost:8000/docs
- Dashboard:  http://localhost:3000
- Postgres:   localhost:5432  (user: jobagent / pass: jobagent)

On first boot the backend runs migrations and seeds an example master résumé at
`backend/data/master_resume.example.json`. Copy it to
`backend/data/master_resume.json` and fill in your real details — it is the
**single source of truth** for your factual experience.

### LLM choice

Primary is the **AiCredits** OpenAI-compatible gateway (paid, INR) running
**`anthropic/claude-3-haiku`**, with free **Groq Llama 3.3 70B** as automatic
fallback. Switch the primary via `LLM_PROVIDER` (`aicredits` | `gemini` | `groq`
| `claude`).

> ⚠️ **Use a NON-thinking model with AiCredits.** Reasoning models spend the
> `max_tokens` budget on hidden thinking and truncate JSON output — e.g.
> `gemini-2.0-flash` on the gateway maps to gemini-2.5-flash (thinking) and
> breaks ranking. Verified-good cheap choices: `anthropic/claude-3-haiku`,
> `gemini-2.0-flash-lite`.

## The workflow, step by step

1. **Pipeline runs** (every 12h, or `POST /api/runs/trigger`): fetch → geo gate →
   fresher gate → ingest → **rank → stop**.
2. **Review** the shortlist on the dashboard **Shortlist** tab (jobs ≥ threshold,
   best first).
3. Click **Tailor & prepare** on one you like → download the tailored résumé +
   cover letter.
4. **Apply yourself** on the source site, then click **Mark as applied**.

### Richer LinkedIn jobs (optional, local)

```bash
cd backend
python -m app.automation.linkedin_discover --rank   # log in once; it scrapes + ranks
```
Discovery only — it ingests jobs for ranking and never applies. Your login
persists in `backend/storage/linkedin_profile`.

## Local development (no Docker)

### Backend
```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium                          # only needed for LinkedIn discovery / auto mode
alembic upgrade head                                 # against a reachable DB (see note)
uvicorn app.main:app --reload
```

> **DB host note:** `.env` `DATABASE_URL` uses the docker-compose host `db`,
> which only resolves inside the compose network. Local CLIs (alembic, the
> LinkedIn runner) connect via `localhost:5432` (compose publishes it). The
> LinkedIn runner rewrites the host automatically; for alembic run:
> `DATABASE_URL=postgresql+psycopg://jobagent:jobagent@localhost:5432/jobagent alembic upgrade head`.

### Frontend
```bash
cd frontend
npm install
npm run dev
```

## Triggering a run manually

```bash
python -m app.scheduler.jobs run-once     # inside the backend container or local venv
# or
curl -X POST http://localhost:8000/api/runs/trigger
```

## Configuration (.env)

See `.env.example` for the full list. Key knobs:

| Variable                    | Default                     | Notes                                                        |
|-----------------------------|-----------------------------|--------------------------------------------------------------|
| `LLM_PROVIDER`              | `aicredits`                 | `aicredits` \| `gemini` \| `groq` \| `claude`.               |
| `LLM_FALLBACK_PROVIDER`     | `groq`                      | Auto-failover if primary errors. Empty to disable.           |
| `AICREDITS_API_KEY`         | —                           | Paid gateway key (primary).                                  |
| `AICREDITS_MODEL`           | `anthropic/claude-3-haiku`  | **Use a non-thinking model** (see LLM choice above).         |
| `GROQ_API_KEY`              | —                           | Free fallback. console.groq.com.                             |
| `APPLY_MODE`                | `approval`                  | `approval` (review-first) \| `auto` (legacy auto-apply).     |
| `MIN_RANK_TO_APPLY`         | `70`                        | Shortlist threshold (0–100).                                 |
| `EXPERIENCE_FILTER_ENABLED` | `true`                      | Fresher gate.                                                |
| `MAX_EXPERIENCE_YEARS`      | `2`                         | Drop roles requiring more than this.                         |
| `GEO_FILTER_ENABLED`        | `true`                      | India / remote / sponsored only.                             |
| `SCHEDULE_CRON_MORNING`     | `0 9 * * *`                 | IST.                                                         |
| `SCHEDULE_CRON_EVENING`     | `0 21 * * *`                | IST (12h after morning).                                     |
| `WORKDAY_TENANTS`           | `ms.wd5...\|ms\|External,…` | `host\|tenant\|site[\|Display]`, comma-separated.            |
| `ORACLE_TENANTS`            | `jpmc.fa...\|CX_1001,…`     | `host\|siteNumber[\|Display]`, comma-separated.              |
| `LINKEDIN_DISCOVER_MAX`     | `40`                        | Max jobs per local LinkedIn discovery run.                   |

## Project layout

```
ai-job-agent/
├── backend/        FastAPI app, sources, services, filters, automation, scheduler
├── frontend/       Next.js 14 dashboard (Dashboard / Shortlist / Applications / Settings)
├── docker-compose.yml
├── .env.example
└── README.md
```

See `backend/README.md`, `DEPLOY.md`, and `PROMPTS.md` for deeper notes.

## Safety & ToS

- Greenhouse / Lever / YC / Workday / Oracle expose programmatic endpoints used
  for discovery. LinkedIn & Naukri are scraped politely at low volume and are
  **rank-only** — never auto-submitted by the pipeline.
- The optional **LinkedIn logged-in discovery** runner reads job data only and
  never applies; note that scraping LinkedIn is against its User Agreement, so
  it is local, attended, and rate-limited.
- Default `APPLY_MODE=approval` means **you** review and submit every
  application — no surprise auto-submits.
- Credentials live in env vars only, never in the database (`.env` is gitignored).
- The LLM is instructed to keep all résumé edits factually grounded in the master
  résumé; identity fields are force-restored in code.

## License

MIT — see `LICENSE`.
