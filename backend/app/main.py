"""FastAPI entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import (
    routes_admin,
    routes_applications,
    routes_auth,
    routes_dashboard,
    routes_guest,
    routes_jobs,
    routes_preferences,
    routes_resume,
    routes_runs,
    routes_settings,
    routes_watchlist,
)
from app.config import settings
from app.utils.logger import log

_DEFAULT_JWT_SECRET = "dev-insecure-change-me-please-min-32-characters-long"


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: D401
    log.info(f"AI Job Agent starting in {settings.app_env} mode")
    # Fail loudly if a production deploy is still using the insecure default
    # signing secret (anyone could forge tokens). Never log the secret itself.
    if settings.app_env.lower() == "prod":
        if settings.jwt_secret == _DEFAULT_JWT_SECRET or len(settings.jwt_secret) < 32:
            raise RuntimeError(
                "JWT_SECRET is missing/weak in production. Set a strong random "
                "JWT_SECRET (>=32 chars) — see .env.example."
            )
    yield
    log.info("AI Job Agent shutting down")


def _cors_origins() -> list[str]:
    """Explicit allow-list built from FRONTEND_URL (+ localhost for dev).
    Avoids the insecure wildcard while still supporting local development."""
    origins = {
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    }
    if settings.frontend_url:
        origins.add(settings.frontend_url.rstrip("/"))
    return sorted(o for o in origins if o)


app = FastAPI(
    title="AI Job Agent",
    version="0.1.0",
    description="Automated job search, AI resume tailoring, and auto-apply pipeline.",
    lifespan=lifespan,
)

# Auth uses Bearer tokens (not cookies), so we don't need credentialed CORS;
# an explicit origin allow-list is both correct and safer than the wildcard.
# Vercel preview deployments (https://<branch>-<proj>.vercel.app) are matched
# via regex so PR previews keep working without listing each one.
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(routes_auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(routes_jobs.router, prefix="/api/jobs", tags=["jobs"])
app.include_router(
    routes_applications.router, prefix="/api/applications", tags=["applications"]
)
app.include_router(routes_resume.router, prefix="/api/resume", tags=["resume"])
app.include_router(routes_runs.router, prefix="/api/runs", tags=["runs"])
app.include_router(routes_settings.router, prefix="/api/settings", tags=["settings"])
app.include_router(
    routes_dashboard.router, prefix="/api/dashboard", tags=["dashboard"]
)
app.include_router(routes_admin.router, prefix="/api/admin", tags=["admin"])
app.include_router(
    routes_preferences.router, prefix="/api/preferences", tags=["preferences"]
)
app.include_router(routes_watchlist.router, prefix="/api/watchlist", tags=["watchlist"])
app.include_router(routes_guest.router, prefix="/api/guest", tags=["guest"])

# Serve generated PDFs (read-only)
app.mount("/files", StaticFiles(directory=str(settings.storage_dir)), name="files")


@app.get("/", tags=["meta"])
def root() -> dict:
    return {
        "name": "AI Job Agent",
        "version": "0.1.0",
        "docs": "/docs",
    }


@app.get("/healthz", tags=["meta"])
def healthz() -> dict:
    return {"status": "ok"}
