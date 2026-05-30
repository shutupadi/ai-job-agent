"""Cover-letter generator (Claude) + PDF render + DB persist."""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import settings
from app.db import models
from app.services.llm import llm
from app.services.pdf_renderer import render_cover_letter_pdf
from app.utils.logger import log


def generate_for_job(
    db: Session,
    job: models.Job,
    resume_json: dict,
    user_id: str | None = None,
) -> models.CoverLetter:
    prompt = llm.load_prompt("cover_letter").format(
        resume_json=json.dumps(resume_json, indent=2),
        job_title=job.title,
        company=job.company,
        job_description=(job.description or "")[:10000],
    )
    text = llm.complete(
        system="You write concise, honest cover letters for engineering students.",
        user=prompt,
        max_tokens=900,
    )
    text = text.strip()

    # Sign with the résumé's own name (multi-user) — fall back to env candidate.
    signer = (resume_json or {}).get("name") or settings.candidate_full_name
    safe_company = "".join(c for c in job.company.lower() if c.isalnum() or c in "-_")[:32]
    uid = (user_id or "shared")[:8]
    pdf_path = Path(settings.storage_dir) / "cover_letters" / f"{uid}_{safe_company}_{job.id[:8]}.pdf"
    render_cover_letter_pdf(text, signer, pdf_path)

    cl = models.CoverLetter(
        user_id=user_id,
        job_id=job.id,
        text=text,
        pdf_path=str(pdf_path),
    )
    db.add(cl)
    db.flush()
    log.info(f"Cover letter {cl.id} → {pdf_path}")
    return cl
