"""
Build a scoring.UserCtx from the DB.

Centralises every per-user read the ranker needs (résumé profile + preferences +
watchlist + company-tier overrides + feedback learning) so pipeline pre-filter
and ranking share one source of truth. Loaded ONCE per user per run.
"""

from __future__ import annotations

import re
from typing import Optional

from sqlalchemy.orm import Session

from app.db import models
from app.services import company_quality, ranking, relevance
from app.services.scoring import UserCtx

_TOK = re.compile(r"[a-z]+")


def _flat_skills(resume_json: dict) -> set[str]:
    out: set[str] = set()
    skills = resume_json.get("skills") or {}
    if isinstance(skills, dict):
        for v in skills.values():
            for s in (v or []):
                out.add(str(s).lower().strip())
    elif isinstance(skills, list):
        for s in skills:
            out.add(str(s).lower().strip())
    for s in (resume_json.get("primary_skills") or []):
        out.add(str(s).lower().strip())
    return {s for s in out if s}


def load_company_overrides(db: Session) -> dict[str, int]:
    rows = db.query(models.CompanyTierOverride.company_norm, models.CompanyTierOverride.tier).all()
    return {norm: tier for norm, tier in rows}


def build_user_ctx(
    db: Session,
    user_id: str,
    resume_json: dict,
    fresher: bool,
    *,
    company_overrides: Optional[dict[str, int]] = None,
) -> UserCtx:
    terms = relevance.candidate_terms(resume_json)
    technical = relevance.role_is_technical(resume_json, terms)
    years = ranking.candidate_years(resume_json)
    target_titles = resume_json.get("target_titles") or []
    if not isinstance(target_titles, list):
        target_titles = []

    prefs = db.get(models.UserPreferences, user_id)

    # Preferences can also force fresher mode.
    if prefs and (prefs.experience_level or "").lower() == "fresher":
        fresher = True

    # Watchlist → {company_norm: priority}
    watchlist: dict[str, str] = {}
    for w in db.query(models.WatchlistCompany).filter_by(user_id=user_id).all():
        watchlist[w.company_norm] = w.priority

    # Feedback learning + hidden companies.
    hidden: set[str] = {n for n, p in watchlist.items() if p == "block"}
    liked: set[str] = set()
    disliked: set[str] = set()
    for fb in db.query(models.JobFeedback).filter_by(user_id=user_id).all():
        if fb.action == "hide_company" and fb.company_norm:
            hidden.add(fb.company_norm)
        toks = set(fb.terms or [])
        if fb.action == "more_like_this":
            liked |= toks
        elif fb.action == "not_relevant":
            disliked |= toks
    # Don't let a term be both liked and disliked.
    disliked -= liked

    return UserCtx(
        years=years,
        fresher=fresher,
        technical=technical,
        skills=_flat_skills(resume_json),
        terms=terms,
        target_titles=[str(t) for t in target_titles][:8],
        min_salary_lpa=(prefs.min_salary_lpa if prefs else None),
        preferred_cities=(prefs.preferred_cities if prefs else []) or [],
        work_modes=(prefs.work_modes if prefs else []) or [],
        excluded_keywords=(prefs.excluded_keywords if prefs else []) or [],
        must_have_skills=(prefs.must_have_skills if prefs else []) or [],
        blocked_industries=(prefs.blocked_industries if prefs else []) or [],
        watchlist=watchlist,
        company_overrides=company_overrides if company_overrides is not None else load_company_overrides(db),
        hidden_companies=hidden,
        liked_terms=liked,
        disliked_terms=disliked,
    )


def title_terms(title: str) -> list[str]:
    """Distinctive tokens from a job title, used to store feedback 'terms'."""
    stop = {"the", "and", "for", "with", "of", "to", "in", "a", "an", "ii", "iii",
            "engineer", "senior", "junior", "lead", "staff"}
    return [t for t in _TOK.findall((title or "").lower()) if len(t) > 2 and t not in stop][:8]
