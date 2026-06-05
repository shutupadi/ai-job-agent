"""
AI ranking — per user × job, 0..100 with a 6-factor breakdown.

Each user gets their own Ranking row for a job, scored against THEIR uploaded
résumé. The job pool itself is shared.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from typing import Any, Dict

from sqlalchemy.orm import Session

from app.config import settings
from app.db import models
from app.services.llm import llm
from app.utils.logger import log


def _year(s) -> int | None:
    m = re.search(r"(19|20)\d{2}", str(s or ""))
    return int(m.group()) if m else None


def _estimate_years(experience) -> int:
    """Rough total years from experience entries' start/end dates (fallback)."""
    if not isinstance(experience, list):
        return 0
    now = dt.datetime.utcnow().year
    total = 0
    for e in experience:
        if not isinstance(e, dict):
            continue
        start = _year(e.get("start"))
        end = _year(e.get("end")) or now
        if start:
            total += max(0, end - start)
    return total


def experience_level(years: int) -> str:
    if years < 2:
        return "entry / new-grad"
    if years < 6:
        return "mid-level"
    return "senior"


def candidate_years(resume_json: dict) -> int:
    """Total years of experience for a parsed résumé. Prefers the parser's
    explicit `experience_years`; falls back to estimating from job dates."""
    years = resume_json.get("experience_years")
    if not isinstance(years, (int, float)) or years == 0:
        est = _estimate_years(resume_json.get("experience"))
        years = max(int(years or 0), est)
    return int(years or 0)


# Top product companies + investment banks / quant funds — these get a relevance
# bonus so they float to the top of the shortlist (user-requested priority).
TOP_COMPANIES = {
    "google", "alphabet", "meta", "facebook", "amazon", "microsoft", "apple",
    "netflix", "stripe", "databricks", "nvidia", "openai", "anthropic", "uber",
    "airbnb", "atlassian", "salesforce", "adobe", "snowflake", "coinbase",
    "datadog", "figma", "dropbox", "instacart", "doordash", "pinterest",
    "robinhood", "plaid", "brex", "ramp", "linkedin", "spotify", "cloudflare",
    "mongodb", "confluent", "hashicorp", "palantir", "scale ai", "roblox",
    "reddit", "notion", "canva", "razorpay", "cred", "zerodha", "flipkart",
    "swiggy", "zomato", "phonepe", "groww", "postman", "intuit", "servicenow",
    # investment banks / quant / finance
    "goldman sachs", "morgan stanley", "jpmorgan", "jp morgan", "j.p. morgan",
    "bank of america", "barclays", "citi", "citigroup", "deutsche bank", "ubs",
    "hsbc", "wells fargo", "blackrock", "blackstone", "citadel", "jane street",
    "two sigma", "de shaw", "d. e. shaw", "optiver", "jump trading",
    "hudson river", "tower research", "millennium", "point72", "susquehanna",
}


def _company_boost(company: str) -> int:
    c = (company or "").lower()
    return 8 if any(t in c for t in TOP_COMPANIES) else 0


def _recency_boost(job: "models.Job") -> int:
    when = getattr(job, "posted_at", None) or getattr(job, "discovered_at", None)
    if not when:
        return 0
    try:
        age_days = (dt.datetime.utcnow() - when).days
    except Exception:
        return 0
    if age_days <= 1:
        return 6
    if age_days <= 3:
        return 4
    if age_days <= 7:
        return 2
    return 0


def candidate_profile(resume_json: dict, fresher: bool = False) -> str:
    """Compact, EXPERIENCE-AWARE profile for the ranking prompt. Works for any
    level (fresher → senior) from the user's own résumé. When `fresher` is set
    (per-user fresher mode), the candidate is framed as a 0-experience new-grad
    regardless of what the parser guessed."""
    skills = resume_json.get("skills") or {}
    flat_skills = []
    if isinstance(skills, dict):
        for v in skills.values():
            flat_skills.extend(v or [])
    else:
        flat_skills = list(skills)

    years = candidate_years(resume_json)
    if fresher:
        years = 0
        level = "entry / new-grad (FRESHER MODE — only entry-level roles)"
    else:
        level = experience_level(years)

    titles = [
        e.get("title")
        for e in (resume_json.get("experience") or [])
        if isinstance(e, dict) and e.get("title")
    ][:3]

    target_titles = resume_json.get("target_titles") or []
    if not isinstance(target_titles, list):
        target_titles = []

    return json.dumps(
        {
            "name": resume_json.get("name"),
            "summary": resume_json.get("summary"),
            "professional_experience_years": years,
            "experience_level": level,
            "role_direction": resume_json.get("role_direction") or "",
            "target_titles": [str(t) for t in target_titles][:6],
            "recent_titles": titles,
            "min_salary_lpa": settings.min_salary_lpa,
            "skills": flat_skills,
        },
        indent=2,
    )


def rank_job_for_user(
    db: Session, user_id: str, resume_json: dict, job: models.Job, fresher: bool = False
) -> models.Ranking:
    """Score one job for one user; upsert their Ranking row. The LLM 0-100 score
    is then nudged by deterministic recency + top-company boosts."""
    prompt = llm.load_prompt("rank_job").format(
        candidate_profile=candidate_profile(resume_json, fresher=fresher),
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

    base = int(payload.get("overall", 0))
    # Only lift jobs that are already a decent fit — don't let company/recency
    # bonuses inflate clearly-irrelevant roles (e.g. an HR role at a top company).
    bonus = (_recency_boost(job) + _company_boost(job.company)) if base >= 50 else 0
    rk.rank_score = max(0, min(100, base + bonus))
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
