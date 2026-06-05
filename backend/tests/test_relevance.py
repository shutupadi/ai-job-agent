"""Unit tests for résumé↔job relevance + role-direction (app.services.relevance)."""

from __future__ import annotations

from app.services import relevance as rel


_TECH_RESUME = {
    "role_direction": "software engineering",
    "target_titles": ["Software Engineer", "Backend Engineer", "SDE I"],
    "summary": "Backend engineer who builds Python/FastAPI services on AWS.",
    "skills": {
        "languages": ["Python", "Java", "SQL"],
        "infra": ["Docker", "Kubernetes", "AWS"],
    },
    "experience": [{"title": "Software Engineering Intern"}],
}

_SALES_RESUME = {
    "role_direction": "sales",
    "target_titles": ["Account Executive", "Sales Manager"],
    "summary": "Quota-crushing account executive.",
    "skills": {"concepts": ["Salesforce", "Negotiation", "Pipeline"]},
    "experience": [{"title": "Account Executive"}],
}


def test_role_is_technical_from_direction():
    assert rel.role_is_technical(_TECH_RESUME) is True
    assert rel.role_is_technical(_SALES_RESUME) is False


def test_role_is_technical_fallback_to_markers():
    # No explicit role_direction → fall back to skill-marker overlap.
    resume = {"skills": {"languages": ["Python", "Go"], "infra": ["Kubernetes"]}}
    assert rel.role_is_technical(resume) is True
    assert rel.role_is_technical({"skills": {"concepts": ["Excel"]}}) is False


def test_candidate_terms_includes_skills_and_titles():
    terms = rel.candidate_terms(_TECH_RESUME)
    assert "python" in terms
    assert "aws" in terms


def test_wrong_direction_drops_sales_for_technical():
    assert rel.is_wrong_direction(True, "Sales Engineer") is True
    assert rel.is_wrong_direction(True, "Technical Recruiter") is True
    assert rel.is_wrong_direction(True, "Account Executive") is True
    assert rel.is_wrong_direction(True, "Marketing Manager") is True


def test_wrong_direction_keeps_real_engineering():
    assert rel.is_wrong_direction(True, "Software Engineer") is False
    assert rel.is_wrong_direction(True, "Backend Engineer, Sales Platform") is False
    assert rel.is_wrong_direction(True, "Senior Data Engineer") is False


def test_wrong_direction_noop_for_nontechnical_candidate():
    # A salesperson SHOULD see sales roles.
    assert rel.is_wrong_direction(False, "Account Executive") is False


def test_relevance_score_prefers_on_target_titles():
    terms = rel.candidate_terms(_TECH_RESUME)
    technical = rel.role_is_technical(_TECH_RESUME, terms)
    swe = rel.relevance_score(terms, technical, "Backend Software Engineer", "Python, AWS")
    sales = rel.relevance_score(terms, technical, "Enterprise Sales Executive", "quota")
    assert swe > sales
