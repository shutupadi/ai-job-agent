"""Unit tests for the per-user pre-filter (pipeline.passes_prefilter)."""

from __future__ import annotations

import pytest

from app.services import experience_filter as ef
from app.services.pipeline import passes_prefilter


@pytest.fixture(autouse=True)
def _cfg(monkeypatch):
    monkeypatch.setattr(ef.settings, "experience_filter_enabled", True)
    monkeypatch.setattr(ef.settings, "max_experience_years", 2)


def test_fresher_drops_senior_and_wrong_direction():
    # Technical fresher
    assert passes_prefilter(True, 0, True, "Software Engineer", "new grad") is True
    assert passes_prefilter(True, 0, True, "Senior Software Engineer", "") is False
    # Wrong profession is dropped even if level would be fine.
    assert passes_prefilter(True, 0, True, "Sales Engineer", "entry level") is False


def test_experienced_keeps_senior_role_match():
    # Mid-level technical candidate
    assert passes_prefilter(True, 4, False, "Senior Backend Engineer", "") is True
    assert passes_prefilter(True, 4, False, "Engineering Manager", "") is False
    assert passes_prefilter(True, 4, False, "Account Executive", "") is False


def test_nontechnical_candidate_keeps_sales():
    # A salesperson (not technical) should keep sales roles.
    assert passes_prefilter(False, 3, False, "Account Executive", "") is True
