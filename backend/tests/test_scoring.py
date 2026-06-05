"""Unit tests for the hybrid scorer (app.services.scoring)."""

from __future__ import annotations

import pytest

from app.services import experience_filter as ef
from app.services.scoring import UserCtx, label_for, score_job, skill_match


@pytest.fixture(autouse=True)
def _cfg(monkeypatch):
    monkeypatch.setattr(ef.settings, "experience_filter_enabled", True)
    monkeypatch.setattr(ef.settings, "max_experience_years", 2)


def _swe_ctx(**over) -> UserCtx:
    base = dict(
        years=3,
        fresher=False,
        technical=True,
        skills={"python", "java", "aws", "fastapi", "sql"},
        terms={"python", "backend", "aws", "fastapi"},
        target_titles=["Software Engineer", "Backend Engineer"],
    )
    base.update(over)
    return UserCtx(**base)


def test_label_thresholds():
    assert label_for(90) == "excellent"
    assert label_for(70) == "good"
    assert label_for(50) == "maybe"
    assert label_for(20) == "not_recommended"


def test_skill_match_matched_and_missing():
    matched, missing, pct = skill_match(
        {"python", "aws"}, ["Python", "AWS", "Kubernetes", "Terraform"]
    )
    assert "Python" in matched and "AWS" in matched
    assert "Kubernetes" in missing and "Terraform" in missing
    assert pct == 50


def test_good_role_scores_high():
    r = score_job(
        _swe_ctx(),
        title="Backend Software Engineer",
        company="Stripe",
        description="Build Python/FastAPI services on AWS. " * 20,
        ats_keywords=["Python", "AWS", "FastAPI"],
        llm_overall=85,
        llm_breakdown={"ats_match": 85, "shortlist_likelihood": 80},
    )
    assert r["exclude"] is False
    assert r["score"] >= 70
    assert r["label"] in ("excellent", "good")
    assert "Python" in r["signals"]["matched_skills"]


def test_wrong_direction_is_capped():
    r = score_job(
        _swe_ctx(),
        title="Enterprise Sales Executive",
        company="Google",  # brand must NOT rescue a wrong role
        description="Hit quota selling our platform. " * 20,
        ats_keywords=["Salesforce"],
        llm_overall=70,
        llm_breakdown={"ats_match": 30, "shortlist_likelihood": 20},
    )
    assert r["score"] <= 25
    assert r["label"] == "not_recommended"


def test_suspicious_is_excluded():
    r = score_job(
        _swe_ctx(),
        title="Work From Home Data Entry",
        company="ABC Staffing Consultancy",
        description="registration fee required. unlimited earning. " * 10,
        ats_keywords=[],
    )
    assert r["exclude"] is True


def test_excluded_keyword_excludes():
    ctx = _swe_ctx(excluded_keywords=["unpaid"])
    r = score_job(
        ctx,
        title="Backend Engineer",
        company="Acme",
        description="This is an unpaid position. " * 20,
        ats_keywords=["Python"],
        llm_overall=80,
        llm_breakdown={"ats_match": 80, "shortlist_likelihood": 70},
    )
    assert r["exclude"] is True


def test_blocked_company_excluded():
    ctx = _swe_ctx(watchlist={"acme": "block"})
    r = score_job(
        ctx, title="Backend Engineer", company="Acme",
        description="Build APIs. " * 20, ats_keywords=["Python"],
        llm_overall=80, llm_breakdown={"ats_match": 80, "shortlist_likelihood": 70},
    )
    assert r["exclude"] is True


def test_hidden_company_excluded():
    ctx = _swe_ctx(hidden_companies={"acme"})
    r = score_job(
        ctx, title="Backend Engineer", company="Acme Inc",
        description="Build APIs. " * 20, ats_keywords=["Python"],
        llm_overall=80, llm_breakdown={"ats_match": 80},
    )
    assert r["exclude"] is True


def test_watchlist_boost_only_with_fit():
    base = dict(
        title="Backend Software Engineer", company="Stripe",
        description="Python FastAPI AWS. " * 20, ats_keywords=["Python", "AWS"],
        llm_overall=80, llm_breakdown={"ats_match": 80, "shortlist_likelihood": 75},
    )
    plain = score_job(_swe_ctx(), **base)
    watched = score_job(_swe_ctx(watchlist={"stripe": "prioritize"}), **base)
    assert watched["score"] >= plain["score"]
    assert watched["signals"]["watchlisted"] is True


def test_feedback_disliked_terms_penalize():
    base = dict(
        title="Frontend Engineer", company="Acme",
        description="React UI work. " * 20, ats_keywords=["React"],
        llm_overall=70, llm_breakdown={"ats_match": 70, "shortlist_likelihood": 65},
    )
    plain = score_job(_swe_ctx(), **base)
    disliked = score_job(_swe_ctx(disliked_terms={"frontend"}), **base)
    assert disliked["score"] < plain["score"]


def test_company_tier_influences_score():
    base = dict(
        title="Backend Software Engineer",
        description="Python FastAPI AWS. " * 20, ats_keywords=["Python", "AWS"],
        llm_overall=75, llm_breakdown={"ats_match": 75, "shortlist_likelihood": 70},
    )
    t1 = score_job(_swe_ctx(), company="Google", **base)
    t4 = score_job(_swe_ctx(), company="Unknown Co", **base)
    assert t1["score"] >= t4["score"]
    assert t1["signals"]["company_tier"] == 1
