# Backend

FastAPI + SQLAlchemy + Alembic + APScheduler + Playwright + reportlab.

## Modules

```
app/
├── api/              FastAPI routers (jobs, applications, resume, runs, settings, dashboard)
├── automation/
│   ├── apply.py            Playwright auto-apply (legacy APPLY_MODE=auto only)
│   ├── form_filler.py      shared form-fill helpers
│   └── linkedin_discover.py  LOCAL logged-in LinkedIn DISCOVERY (never applies)
├── db/               SQLAlchemy models + session
├── schemas/          Pydantic request/response models
├── scheduler/        APScheduler daemon + CLI
├── services/
│   ├── llm.py              Multi-provider LLM (AiCredits primary, Groq fallback, Gemini/Claude opt)
│   ├── geo_filter.py       India / remote / sponsored gate
│   ├── experience_filter.py  fresher / entry-level gate (drops senior + high-YOE)
│   ├── resume_engine.py    master-résumé + JD tailoring
│   ├── cover_letter.py     short JD-aware cover letter
│   ├── ranking.py          AI ranking (0–100), fresher-aware
│   ├── pdf_renderer.py     reportlab → PDF
│   ├── dedupe.py           job upsert + dedupe
│   ├── export.py           ranked shortlist worklist (CSV)
│   ├── pipeline.py         end-to-end orchestrator (rank-only in approval mode)
│   └── notifier.py         SMTP run summary
├── sources/          greenhouse, lever, ycombinator, workday, oracle (real);
│                     linkedin, naukri (public, rank-only); indeed, wellfound (stub)
├── utils/            logger, helpers
├── bootstrap.py      first-boot seed
├── config.py         pydantic-settings (loads repo-root .env)
└── main.py           FastAPI entrypoint (+ /files static mount for PDFs)
```

## Pipeline stages (`services/pipeline.py`)

`fetch → geo gate → fresher gate → ingest → rank → (stop in approval mode)`.
In `APPLY_MODE=auto` it additionally tailors + auto-applies the top candidates;
`rank_new_jobs(limit)` is shared with the LinkedIn discovery runner.

## CLIs

```
# Pipeline scheduler loop (every 12h)
python -m app.scheduler.jobs daemon

# One-shot pipeline
python -m app.scheduler.jobs run-once --trigger=manual

# LinkedIn logged-in discovery (local, attended; ingests + optionally ranks; never applies)
python -m app.automation.linkedin_discover --rank

# Bootstrap example master résumé
python -m app.bootstrap

# Migrations (locally, target the published localhost port — the compose host
# "db" only resolves inside the compose network):
DATABASE_URL=postgresql+psycopg://jobagent:jobagent@localhost:5432/jobagent alembic upgrade head
alembic revision --autogenerate -m "msg"
```

## Editing your master résumé

The bootstrap script writes `backend/data/master_resume.json`. Edit that file
freely — it is the **single source of truth** for your factual experience. The
LLM is instructed never to invent content outside this file, and identity fields
(name/email/phone) are force-restored in `resume_engine._validate`.

## LLM providers (`services/llm.py`)

`LLM_PROVIDER` selects the primary; `LLM_FALLBACK_PROVIDER` the safety net.

- `aicredits` — OpenAI-compatible gateway (paid). Set `AICREDITS_MODEL` to a
  **non-thinking** model (`anthropic/claude-3-haiku`). Reasoning/"thinking"
  models spend the token budget internally and truncate JSON.
- `gemini` / `groq` — free tiers. `claude` — native Anthropic API.

## Adding a source

1. Create `app/sources/<name>.py` exposing `name = "<name>"` and
   `fetch() -> Iterable[RawJob]` (set `auto_apply=False` for login/anti-bot sites).
2. Register it in `app/sources/registry.py` behind a settings flag.
3. Add the flag to `app/config.py` and `.env.example`.

New jobs flow through the geo + experience filters automatically before ranking.
