"""FastAPI entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import (
    routes_applications,
    routes_dashboard,
    routes_jobs,
    routes_resume,
    routes_runs,
    routes_settings,
)
from app.config import settings
from app.utils.logger import log


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: D401
    log.info(f"AI Job Agent starting in {settings.app_env} mode")
    yield
    log.info("AI Job Agent shutting down")


app = FastAPI(
    title="AI Job Agent",
    version="0.1.0",
    description="Automated job search, AI resume tailoring, and auto-apply pipeline.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
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
