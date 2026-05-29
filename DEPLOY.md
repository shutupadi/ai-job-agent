# Deployment guide

## ⭐ Free public demo (Vercel + Render) — best for a resume link

Goal: a shareable URL + a visitor count, for ₹0.

**1. Backend + DB → Render (Blueprint).**
- Push this repo to GitHub. In Render → **New → Blueprint**, point it at the repo;
  it reads `render.yaml` (FastAPI web service on the free plan + free Postgres).
- In the service's **Environment**, set the secret vars marked `sync: false`:
  `AICREDITS_API_KEY`, `GROQ_API_KEY`, `CANDIDATE_FULL_NAME`, `CANDIDATE_EMAIL`, …
- Note the public URL, e.g. `https://ai-job-agent-backend.onrender.com`.
- *Free caveats:* the service **sleeps after ~15 min idle** (first hit is slow) and
  free Postgres **expires in ~90 days**. Fine for a demo.

**2. Frontend → Vercel.**
- Vercel → **New Project** → import the repo → set **Root Directory = `frontend`**
  (it picks up `frontend/vercel.json` / Next.js automatically).
- Add env var **`NEXT_PUBLIC_API_BASE`** = your Render backend URL (from step 1).
- Deploy → you get a free link like `https://ai-job-agent-aditya.vercel.app`.

**3. Twice-daily runs without a paid worker.**
- The GitHub Actions cron (`.github/workflows/ci.yml` → `remote-trigger`) hits
  `POST /api/runs/trigger` at 09:00 & 21:00 IST.
- Just add a repo secret **`JOBAGENT_API_URL`** = your Render URL. (No secret = it
  skips quietly.) This also wakes the sleeping free backend.

**4. Visitor count (free).**
- Already wired: `@vercel/analytics` is mounted in `app/layout.tsx`. In the Vercel
  project, open the **Analytics** tab and enable it — you'll see visitor counts.
- Not on Vercel? Use **Cloudflare Web Analytics** (free) — paste its one `<script>`
  snippet into `app/layout.tsx`.

> Tip: for a demo that always looks alive even while the backend sleeps, run the
> pipeline once so the DB has ranked jobs, or seed a few sample rows.

---

## A. Local Docker Compose (recommended for development)

```bash
cp .env.example .env
# Edit .env — at minimum set AICREDITS_API_KEY (+ GROQ_API_KEY fallback),
# CANDIDATE_*, and your preferred WORKDAY_TENANTS / ORACLE_TENANTS /
# GREENHOUSE_BOARDS / LEVER_COMPANIES.

docker compose up --build
```

Services:
| name      | port | what                                                  |
|-----------|------|-------------------------------------------------------|
| db        | 5432 | Postgres 16                                           |
| backend   | 8000 | FastAPI (`/docs`)                                     |
| scheduler |  —   | APScheduler daemon firing the pipeline every 12h      |
| frontend  | 3000 | Next.js dashboard                                     |

Trigger a manual run:

```bash
curl -X POST http://localhost:8000/api/runs/trigger
# or
./scripts/run_once.sh
```

## B. VPS / single host

1. Provision a Linux VM with Docker + Docker Compose.
2. `git clone` this repo, copy `.env.example` → `.env`, fill values.
3. `docker compose up -d --build`
4. Put nginx / Caddy in front of ports 3000 + 8000 with TLS.
5. Restrict port 5432 to localhost.

## C. Container hosts (Fly.io / Render / Railway)

Provision two services from this repo:
- **backend** — from `backend/Dockerfile`. Runs migrations + uvicorn.
- **frontend** — from `frontend/Dockerfile`.

Plus a managed Postgres add-on; copy its connection string into
`DATABASE_URL` for the backend service. For the scheduler, either:

- run a third service with command `python -m app.scheduler.jobs daemon`, or
- enable the `remote-trigger` job in `.github/workflows/ci.yml` and let
  GitHub Actions hit `POST /api/runs/trigger` twice a day.

## Production checklist

- [ ] `APP_ENV=prod` and `LOG_LEVEL=INFO` in env.
- [ ] `AICREDITS_API_KEY` set + funded (or `LLM_PROVIDER` points at a free tier);
      rotate the key if it was ever shared. `AICREDITS_MODEL` is a **non-thinking**
      model (e.g. `anthropic/claude-3-haiku`).
- [ ] `APPLY_MODE=approval` (default — review-first). Switch to `auto` only deliberately.
- [ ] `EXPERIENCE_FILTER_ENABLED=true` and `MAX_EXPERIENCE_YEARS` tuned (default 2).
- [ ] `GEO_FILTER_ENABLED` and `INCLUDE_REMOTE` / `INCLUDE_INTERNATIONAL` set to taste.
- [ ] `MAX_RANKS_PER_RUN` sane (≈25); `RATE_LIMIT_SECONDS` ≥ 30 if using auto mode.
- [ ] `HEADLESS_BROWSER=true` on a server, `false` locally to debug.
- [ ] SMTP creds set so you receive the run summary.
- [ ] Postgres backups configured.
- [ ] `WORKDAY_TENANTS` / `ORACLE_TENANTS` / `LEVER_COMPANIES` / `GREENHOUSE_BOARDS`
      tuned to YOUR targets.
- [ ] `data/master_resume.json` edited from the example.
- [ ] LinkedIn/Naukri are rank-only (no auto-submit). Indeed/Wellfound stubs left
      **off**. The LinkedIn logged-in discovery runner is local/attended only.
