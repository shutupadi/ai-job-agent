"""Unit tests for the per-user experience-level gate (experience_filter.level_ok)."""

from __future__ import annotations

import pytest

from app.services import experience_filter as ef


@pytest.fixture(autouse=True)
def _cfg(monkeypatch):
    monkeypatch.setattr(ef.settings, "experience_filter_enabled", True)
    monkeypatch.setattr(ef.settings, "max_experience_years", 2)


def test_candidate_band():
    assert ef.candidate_band(0) == "entry"
    assert ef.candidate_band(1) == "entry"
    assert ef.candidate_band(3) == "mid"
    assert ef.candidate_band(8) == "senior"


# ── fresher mode delegates to the strict entry gate ──
def test_fresher_mode_is_strict():
    assert ef.level_ok("Senior Engineer", "", years=0, fresher=True) is False
    assert ef.level_ok("Software Engineer", "new grad welcome", years=0, fresher=True) is True


# ── entry band (experience_pref='all', ~0-2 yrs) ──
def test_entry_band_blocks_senior_titles_and_high_years():
    assert ef.level_ok("Senior Software Engineer", "", years=1) is False
    assert ef.level_ok("Software Engineer", "5+ years required", years=1) is False
    assert ef.level_ok("Software Engineer", "0-2 years", years=1) is True
    # entry band is a touch looser than fresher: up to 3 yrs is fine.
    assert ef.level_ok("Software Engineer", "3 years experience", years=1) is True


# ── mid band (~2-6 yrs) ──
def test_mid_band_allows_senior_blocks_management_and_intern():
    assert ef.level_ok("Senior Software Engineer", "", years=4) is True
    assert ef.level_ok("Staff Engineer", "", years=4) is False
    assert ef.level_ok("Engineering Manager", "", years=4) is False
    assert ef.level_ok("Director of Engineering", "", years=4) is False
    assert ef.level_ok("Software Engineering Intern", "", years=4) is False
    # Way-too-senior YOE requirement is dropped.
    assert ef.level_ok("Software Engineer", "12+ years required", years=4) is False
    assert ef.level_ok("Software Engineer", "6+ years required", years=4) is True


# ── senior band (6+ yrs) ──
def test_senior_band_keeps_leadership_drops_juniors():
    assert ef.level_ok("Staff Engineer", "", years=8) is True
    assert ef.level_ok("Engineering Manager", "", years=8) is True
    assert ef.level_ok("Principal Engineer", "", years=8) is True
    assert ef.level_ok("Software Engineering Intern", "", years=8) is False
    assert ef.level_ok("New Grad Software Engineer", "", years=8) is False
