"""
AI ranking — 0..100 with a 6-factor breakdown.
"""

from __future__ import annotations

import json
from typing import Any, Dict

from sqlalchemy.orm import Session

from app.config import settings
from app.db import models
from app.services.llm import llm
from app.services.resume_engine import load_master_resume
from app.utils.logger import log


def _candidate_profile() -> str:
    master = load_master_resume()
    skills = master.get("skills") or {}
    flat_skills = []
    if isinstance(skills, dict):
        for v in skills.values():
            flat_skills.extend(v or [])
    else:
        flat_skills = skills
    return json.dumps(
        {
            "name": master.get("name"),
            "current_location": settings.candidate_current_location,
            "expected_ctc_lpa": settings.candidate_expected_ctc_lpa,
            "min_salary_lpa": settings.min_salary_lpa,
            "experience_level": settings.experience_level,
            "seniority": (
                "FRESHER — final-year engineering student, ~0 years professional "
                "experience (internships only). Targeting entry-level / new-grad roles."
            ),
            "professional_experience_years": 0,
            "skills": flat_skills,
            "interests": ["SDE", "AI/ML", "Quant/analyst tech roles"],
        },
        indent=2,
    )


def rank_job(db: Session, job: models.Job) -> Dict[str, Any]:
    # JD trimmed to 4000 chars (~1000 tokens) — Gemini & Groq free tiers are
    # tight, and the JD's first 4000 chars overwhelmingly contain the ranking
    # signal (title, requirements, salary, location). The full text is kept
    # in the DB for downstream resume-tailoring.
    prompt = llm.load_prompt("rank_job").format(
        candidate_profile=_candidate_profile(),
        job_title=job.title,
        company=job.company,
        location=job.location or "Unknown",
        remote="yes" if job.remote else "no",
        salary_text=job.salary_text or "not stated",
        job_description=(job.description or "")[:4000],
    )
    payload = llm.complete_json(
        system="You are a precise tech recruiter. Output JSON only.",
        user=prompt,
        max_tokens=600,
    )
    if not isinstance(payload, dict) or "overall" not in payload:
        raise ValueError(f"Bad ranking payload: {payload!r}")

    job.rank_score = int(payload.get("overall", 0))
    job.rank_breakdown = payload.get("breakdown") or {}
    job.rank_reasoning = payload.get("reasoning") or ""
    ak = payload.get("ats_keywords") or []
    if isinstance(ak, list):
        job.ats_keywords = [str(x) for x in ak]
    job.status = "ranked"
    db.flush()
    log.info(
        f"Ranked {job.company}:{job.title} = {job.rank_score} "
        f"({', '.join(f'{k}:{v}' for k,v in (job.rank_breakdown or {}).items())})"
    )
    return payload
