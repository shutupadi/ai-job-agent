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
    path = Path(settings.data_dir) / "master_resume.json"
    if not path.exists():
        # fall back to example if user hasn't customised yet
        path = Path(settings.data_dir) / "master_resume.example.json"
    if not path.exists():
        raise FileNotFoundError(
            "No master_resume.json found. Run `python -m app.bootstrap` first."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _validate(resume: dict) -> None:
    missing = REQUIRED_KEYS - set(resume.keys())
    if missing:
        raise ValueError(f"Tailored resume missing keys: {missing}")
    # Lock identity fields to the master resume — Claude must not change them
    master = load_master_resume()
    for k in ("name", "email", "phone"):
        if resume.get(k) != master.get(k):
            log.warning(f"Tailored resume changed identity field '{k}'; reverting.")
            resume[k] = master.get(k)


def tailor_for_job(db: Session, job: models.Job) -> models.ResumeVersion:
    master = load_master_resume()
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
    _validate(tailored)
    ats_keywords = tailored.pop("ats_keywords", None) or []

    # Render PDF
    safe_company = "".join(c for c in job.company.lower() if c.isalnum() or c in "-_")[:32]
    pdf_path = Path(settings.storage_dir) / "resumes" / f"{safe_company}_{job.id[:8]}.pdf"
    render_resume_pdf(tailored, pdf_path)

    version = models.ResumeVersion(
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
