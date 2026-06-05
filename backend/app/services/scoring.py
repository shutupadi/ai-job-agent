"""
Hybrid, EXPLAINABLE job scoring.

Combines the LLM's nuanced role/skill judgement with deterministic structured
signals into a single 0–100 score, a human label, and a breakdown the UI shows
verbatim ("why is this job here?").

Weights (sum to 1.0):
    role match            30%
    experience fit        25%
    skill match           20%
    company quality/watch 10%
    recency               10%
    salary / location      5%

Hard rules (applied AFTER weighting — brand never rescues a bad role):
    • wrong profession for a technical CV  → capped + "not_recommended"
    • suspicious / scam posting            → excluded
    • excluded keyword (user pref)         → excluded
    • blocked / hidden company             → excluded
    • missing a user "must-have" skill     → downgraded
    • vague title or very thin description  → downgraded

This module is PURE (no DB, no network) so it is fully unit-testable. Callers
(ranking.py) load the user's profile/preferences/watchlist/feedback and pass
plain values in.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from typing import Optional

from app.services import company_quality, experience_filter, relevance

WEIGHTS = {
    "role": 0.30,
    "experience": 0.25,
    "skills": 0.20,
    "company": 0.10,
    "recency": 0.10,
    "salary_location": 0.05,
}

LABEL_THRESHOLDS = [(80, "excellent"), (65, "good"), (45, "maybe")]


def label_for(score: int) -> str:
    for thresh, label in LABEL_THRESHOLDS:
        if score >= thresh:
            return label
    return "not_recommended"


@dataclass
class UserCtx:
    """Everything the scorer needs about the user (all derived once per run)."""

    years: int = 0
    fresher: bool = False
    technical: bool = True
    skills: set[str] = field(default_factory=set)          # lowercased
    terms: set[str] = field(default_factory=set)           # résumé distinctive terms
    target_titles: list[str] = field(default_factory=list)
    # preferences
    min_salary_lpa: Optional[float] = None
    preferred_cities: list[str] = field(default_factory=list)
    work_modes: list[str] = field(default_factory=list)
    excluded_keywords: list[str] = field(default_factory=list)
    must_have_skills: list[str] = field(default_factory=list)
    blocked_industries: list[str] = field(default_factory=list)
    # watchlist + feedback
    watchlist: dict[str, str] = field(default_factory=dict)   # company_norm -> prioritize|normal|block
    company_overrides: dict[str, int] = field(default_factory=dict)
    hidden_companies: set[str] = field(default_factory=set)   # company_norm
    liked_terms: set[str] = field(default_factory=set)
    disliked_terms: set[str] = field(default_factory=set)


def _clamp(v: float) -> int:
    return int(max(0, min(100, round(v))))


def _role_component(u: UserCtx, title: str, desc: str, llm_ats: Optional[int]) -> int:
    t = (title or "").lower()
    score = 40
    # Target-title hit is the strongest deterministic signal.
    for tt in u.target_titles:
        tt = str(tt).lower().strip()
        if tt and (tt in t or t in tt):
            score += 35
            break
    # Term overlap in the title.
    overlap = sum(1 for term in u.terms if term and term in t)
    score += min(25, overlap * 8)
    if u.technical and any(p in t for p in relevance._TECH_TITLE):
        score += 10
    det = _clamp(score)
    # Blend with the LLM's role/skill judgement when available (it sees the JD).
    if llm_ats is not None:
        return _clamp(0.5 * det + 0.5 * llm_ats)
    return det


def _experience_component(u: UserCtx, title: str, desc: str, llm_shortlist: Optional[int]) -> int:
    ok = experience_filter.level_ok(title, desc, u.years, fresher=u.fresher)
    base = 75 if ok else 15
    if llm_shortlist is not None:
        return _clamp(0.5 * base + 0.5 * llm_shortlist)
    return base


def skill_match(skills: set[str], ats_keywords: list[str]) -> tuple[list[str], list[str], int]:
    """Matched vs missing skills + a 0..100 coverage score, from the JD's ATS
    keywords (what the role wants) against the candidate's skills."""
    kws = [str(k).strip() for k in (ats_keywords or []) if str(k).strip()]
    if not kws:
        return [], [], 60  # neutral when the JD gave us nothing to compare
    matched, missing = [], []
    for kw in kws:
        kwl = kw.lower()
        if any(kwl in s or s in kwl for s in skills if s):
            matched.append(kw)
        else:
            missing.append(kw)
    pct = int(round(100 * len(matched) / max(1, len(kws))))
    return matched[:15], missing[:15], pct


def _company_component(u: UserCtx, company: str) -> tuple[int, int, bool]:
    tier = company_quality.tier_for(company, u.company_overrides)
    norm = company_quality.normalize(company)
    pri = u.watchlist.get(norm, "normal")
    watchlisted = pri == "prioritize"
    base = company_quality.tier_score(tier)
    if watchlisted:
        base = min(100, base + 25)
    return _clamp(base), tier, watchlisted


def _recency_component(posted: Optional[dt.datetime], discovered: Optional[dt.datetime]) -> int:
    when = posted or discovered
    if not when:
        return 50
    try:
        age = (dt.datetime.utcnow() - when).days
    except Exception:
        return 50
    if age <= 1:
        return 100
    if age <= 3:
        return 88
    if age <= 7:
        return 75
    if age <= 14:
        return 60
    if age <= 30:
        return 45
    return 25


_SALARY_NUM = re.compile(r"(\d{2,3})\s*(?:lpa|lakh|l\b|k\b|,000)", re.IGNORECASE)


def _salary_location_component(u: UserCtx, location: str, remote: bool, salary_text: str) -> int:
    score = 60
    loc = (location or "").lower()
    if u.preferred_cities:
        if any(c.lower().strip() in loc for c in u.preferred_cities if c.strip()):
            score += 25
        elif remote and "remote" in [w.lower() for w in u.work_modes]:
            score += 15
        else:
            score -= 10
    if remote and ("remote" in [w.lower() for w in u.work_modes] or not u.work_modes):
        score += 10
    # If the user set a min salary and the posting states a (parseable) lower one.
    if u.min_salary_lpa and salary_text:
        m = _SALARY_NUM.search(salary_text)
        if m:
            try:
                val = int(m.group(1))
                if val < u.min_salary_lpa:
                    score -= 20
            except ValueError:
                pass
    return _clamp(score)


def _contains_any(text: str, needles) -> Optional[str]:
    t = (text or "").lower()
    for n in needles:
        n = str(n).lower().strip()
        if n and n in t:
            return n
    return None


def score_job(
    u: UserCtx,
    *,
    title: str,
    company: str,
    description: str,
    location: str = "",
    remote: bool = False,
    salary_text: str = "",
    posted_at: Optional[dt.datetime] = None,
    discovered_at: Optional[dt.datetime] = None,
    ats_keywords: Optional[list[str]] = None,
    llm_overall: Optional[int] = None,
    llm_breakdown: Optional[dict] = None,
) -> dict:
    """Return {score, label, exclude, signals{...}} for one job × user."""
    title = title or ""
    description = description or ""
    bd = llm_breakdown or {}
    llm_ats = bd.get("ats_match") if isinstance(bd.get("ats_match"), (int, float)) else None
    llm_short = bd.get("shortlist_likelihood") if isinstance(bd.get("shortlist_likelihood"), (int, float)) else None

    role = _role_component(u, title, description, llm_ats)
    exp = _experience_component(u, title, description, llm_short)
    matched, missing, skills = skill_match(u.skills, ats_keywords or [])
    company_c, tier, watchlisted = _company_component(u, company)
    recency = _recency_component(posted_at, discovered_at)
    sal_loc = _salary_location_component(u, location, remote, salary_text)

    final = (
        WEIGHTS["role"] * role
        + WEIGHTS["experience"] * exp
        + WEIGHTS["skills"] * skills
        + WEIGHTS["company"] * company_c
        + WEIGHTS["recency"] * recency
        + WEIGHTS["salary_location"] * sal_loc
    )
    final = _clamp(final)

    reasons: list[str] = []
    exclude = False
    norm = company_quality.normalize(company)

    # ── hard rules ──
    if norm in u.hidden_companies or u.watchlist.get(norm) == "block":
        exclude = True
        reasons.append("Company blocked/hidden by you")
    if company_quality.is_suspicious(company, title, description):
        exclude = True
        reasons.append("Looks like a spam/scam or commission-only posting")
    bad_kw = _contains_any(f"{title}\n{description}", u.excluded_keywords)
    if bad_kw:
        exclude = True
        reasons.append(f"Matches your excluded keyword: '{bad_kw}'")
    bad_ind = _contains_any(f"{title}\n{description}", u.blocked_industries)
    if bad_ind:
        exclude = True
        reasons.append(f"Blocked industry: '{bad_ind}'")

    if u.technical and relevance.is_wrong_direction(True, title):
        final = min(final, 25)
        reasons.append("Different profession than your target roles")
    if not experience_filter.level_ok(title, description, u.years, fresher=u.fresher):
        final = min(final, 30)
        reasons.append("Experience level doesn't fit")

    # ── soft adjustments ──
    if u.must_have_skills and not _contains_any(f"{title}\n{description}", u.must_have_skills):
        final = _clamp(final - 12)
        reasons.append("Missing a must-have skill")
    if len(description) < 200:
        final = _clamp(final - 8)
        reasons.append("Vague / thin job description")
    if len(title) < 4 or title.lower() in ("job", "opening", "vacancy", "hiring"):
        final = _clamp(final - 10)
        reasons.append("Vague job title")

    # ── feedback learning ──
    title_toks = set(re.findall(r"[a-z]+", title.lower()))
    if u.disliked_terms & title_toks:
        final = _clamp(final - 15)
        reasons.append("Similar to roles you marked 'Not relevant'")
    if u.liked_terms & title_toks:
        final = _clamp(final + 8)
        reasons.append("Similar to roles you liked")

    if watchlisted and final >= 45:
        reasons.append("On your company watchlist")

    label = "not_recommended" if exclude else label_for(final)

    signals = {
        "role": role,
        "experience": exp,
        "skills": skills,
        "company": company_c,
        "recency": recency,
        "salary_location": sal_loc,
        "matched_skills": matched,
        "missing_skills": missing,
        "company_tier": tier,
        "watchlisted": watchlisted,
        "reasons": reasons[:6],
    }
    return {"score": final, "label": label, "exclude": exclude, "signals": signals}
