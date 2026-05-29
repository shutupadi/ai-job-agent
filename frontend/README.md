# Frontend

Next.js 14 (App Router) + Tailwind + TypeScript.

## Pages

- `/` — Dashboard (metrics, last run, top jobs, “Run pipeline now” button).
- `/jobs` — Browse, filter, search, tailor resume on-demand.
- `/applications` — Track status, approve queued submissions, mark
  interview / offer / rejection.
- `/settings` — Live tweak apply_mode / min_rank / rate limit.

## Dev

```bash
npm install
NEXT_PUBLIC_API_BASE=http://localhost:8000 npm run dev
```

## Build

```bash
npm run build && npm run start
```
