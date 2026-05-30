"""
Resume tailoring engine.

Loads the master resume JSON, asks Claude to rewrite it for a given JD
within strict no-fabrication rules, validates the response, renders a PDF,
persists a ResumeVersion row, returns it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.db import models
from app.services.llm import llm
from app.services.pdf_renderer import render_resume_pdf
from app.utils.logger import log


REQUIRED_KEYS = {"name", "email", "phone", "summary", "skills", "experience"}


def load_master_resume() -> dict:
    """File-based master résumé — used as a fallback / for the single-user CLI."""
    path = Path(settings.data_dir) / "master_resume.json"
    if not path.exists():
        # fall back to example if user hasn't customised yet
        path = Path(settings.data_dir) / "master_resume.example.json"
    if not path.exists():
        raise FileNotFoundError(
            "No master_resume.json found. Run `python -m app.bootstrap` first."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def load_user_resume(db: Session, user_id: str) -> dict | None:
    """A specific user's active (uploaded + parsed) master résumé, or None."""
    row = (
        db.query(models.Resume)
        .filter(models.Resume.user_id == user_id, models.Resume.is_active.is_(True))
        .order_by(models.Resume.created_at.desc())
        .first()
    )
    return row.parsed_json if row else None


def _validate(resume: dict, master: dict) -> None:
    missing = REQUIRED_KEYS - set(resume.keys())
    if missing:
        raise ValueError(f"Tailored resume missing keys: {missing}")
    # Lock identity fields to the master résumé — the LLM must not change them.
    for k in ("name", "email", "phone"):
        if master.get(k) and resume.get(k) != master.get(k):
            log.warning(f"Tailored resume changed identity field '{k}'; reverting.")
            resume[k] = master.get(k)


def tailor_for_job(
    db: Session,
    job: models.Job,
    resume_json: dict | None = None,
    user_id: str | None = None,
) -> models.ResumeVersion:
    master = resume_json or load_master_resume()
    prompt = llm.load_prompt("tailor_resume").format(
        master_resume_json=json.dumps(master, indent=2),
        job_title=job.title,
        company=job.company,
        job_description=(job.description or "")[:12000],
    )
    tailored: Any = llm.complete_json(
        system="You are a precise resume editor. Output JSON only.",
        user=prompt,
        max_tokens=3000,
    )
    if not isinstance(tailored, dict):
        raise ValueError("Tailored resume is not a JSON object")
    _validate(tailored, master)
    ats_keywords = tailored.pop("ats_keywords", None) or []

    # Random, unguessable filename — acts as a capability URL under /files so one
    # user can't enumerate another's PDFs. (Proper signed/auth'd downloads are a
    # scale-later upgrade.)
    import uuid as _uuid

    pdf_path = Path(settings.storage_dir) / "resumes" / f"{_uuid.uuid4().hex}.pdf"
    render_resume_pdf(tailored, pdf_path)

    version = models.ResumeVersion(
        user_id=user_id,
        job_id=job.id,
        label=f"{job.company} – {job.title}"[:255],
        pdf_path=str(pdf_path),
        json_payload=tailored,
        ats_keywords=ats_keywords if isinstance(ats_keywords, list) else [],
    )
    db.add(version)
    db.flush()
    log.info(f"Tailored resume {version.id} → {pdf_path}")
    return version
