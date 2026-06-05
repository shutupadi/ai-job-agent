"""Unit tests for résumé-parse normalisation (app.services.resume_parser._normalize)."""

from __future__ import annotations

import datetime as dt

from app.services import resume_parser as rp


def test_normalize_fills_new_fields_with_defaults():
    p = {"name": "A", "email": "", "phone": "", "summary": "",
         "skills": {}, "experience": []}
    rp._normalize(p)
    for k in ("target_titles", "target_job_types", "domains", "primary_skills"):
        assert isinstance(p[k], list)
    assert isinstance(p["role_direction"], str)
    assert p["seniority"] in ("entry", "mid", "senior")


def test_years_fallback_from_experience_dates():
    # LLM under-reported 0, but dated experience spans ~5 years.
    now = dt.datetime.utcnow().year
    p = {
        "name": "A", "email": "", "phone": "", "summary": "",
        "skills": {}, "experience_years": 0,
        "experience": [{"title": "Engineer", "start": "2018", "end": str(now - 1)}],
    }
    rp._normalize(p)
    assert p["experience_years"] >= 4


def test_seniority_derived_from_years():
    p = {"name": "A", "email": "", "phone": "", "summary": "",
         "skills": {}, "experience": [], "experience_years": 8}
    rp._normalize(p)
    assert p["seniority"] == "senior"


def test_primary_skills_fallback_from_skill_dict():
    p = {"name": "A", "email": "", "phone": "", "summary": "",
         "skills": {"languages": ["Python", "Go"], "infra": ["AWS"]},
         "experience": []}
    rp._normalize(p)
    assert "Python" in p["primary_skills"]
    assert "AWS" in p["primary_skills"]


def test_invalid_seniority_string_is_replaced():
    p = {"name": "A", "email": "", "phone": "", "summary": "",
         "skills": {}, "experience": [], "experience_years": 1,
         "seniority": "rockstar"}
    rp._normalize(p)
    assert p["seniority"] == "entry"
