"""
AI ranking — per user × job, 0..100 with a 6-factor breakdown.

Each user gets their own Ranking row for a job, scored against THEIR uploaded
résumé. The job pool itself is shared.
"""

from __future__ import annotations

import json
from typing import Any, Dict

from sqlalchemy.orm import Session

from app.config import settings
from app.db import models
from app.services.llm import llm
from app.utils.logger import log


def candidate_profile(resume_json: dict) -> str:
    """Compact profile string for the ranking prompt, from a user's résumé."""
    skills = resume_json.get("skills") or {}
    flat_skills = []
    if isinstance(skills, dict):
        for v in skills.values():
            flat_skills.extend(v or [])
    else:
        flat_skills = list(skills)
    return json.dumps(
        {
            "name": resume_json.get("name"),
            "summary": resume_json.get("summary"),
            "seniority": (
                "FRESHER — ~0 years professional experience (internships only). "
                "Targeting entry-level / new-grad roles."
            ),
            "professional_experience_years": 0,
            "min_salary_lpa": settings.min_salary_lpa,
            "skills": flat_skills,
            "interests": ["SDE", "AI/ML", "Quant/analyst tech roles"],
        },
        indent=2,
    )


def rank_job_for_user(
    db: Session, user_id: str, resume_json: dict, job: models.Job
) -> models.Ranking:
    """Score one job for one user; upsert their Ranking row."""
    prompt = llm.load_prompt("rank_job").format(
        candidate_profile=candidate_profile(resume_json),
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
        max_tokens=700,
    )
    if not isinstance(payload, dict) or "overall" not in payload:
        raise ValueError(f"Bad ranking payload: {payload!r}")

    rk = (
        db.query(models.Ranking)
        .filter_by(user_id=user_id, job_id=job.id)
        .first()
    )
    if rk is None:
        rk = models.Ranking(user_id=user_id, job_id=job.id)
        db.add(rk)

    rk.rank_score = int(payload.get("overall", 0))
    rk.rank_breakdown = payload.get("breakdown") or {}
    rk.rank_reasoning = payload.get("reasoning") or ""
    ak = payload.get("ats_keywords") or []
    rk.ats_keywords = [str(x) for x in ak] if isinstance(ak, list) else []
    # Don't clobber a later lifecycle state.
    if rk.status not in ("tailored", "applied"):
        rk.status = "ranked"
    db.flush()
    log.info(f"Ranked [{user_id[:8]}] {job.company}:{job.title} = {rk.rank_score}")
    return payload
