"""
Unit tests for the fresher/entry-level experience gate
(app.services.experience_filter). Pure functions, no network/DB.
"""

from __future__ import annotations

import pytest

from app.services import experience_filter as ef
from app.services.experience_filter import (
    filter_rawjobs,
    is_fresher_friendly,
    keep_rawjob,
    min_required_years,
)
from app.sources.base import RawJob


@pytest.fixture(autouse=True)
def _enabled(monkeypatch):
    # Make the gate's config deterministic regardless of the ambient .env.
    monkeypatch.setattr(ef.settings, "experience_filter_enabled", True)
    monkeypatch.setattr(ef.settings, "max_experience_years", 2)


def _job(title="Software Engineer", description="", **over):
    base = dict(
        source="linkedin",
        external_id="1",
        url="https://example.com/job/1",
        title=title,
        company="Acme",
        description=description,
    )
    base.update(over)
    return RawJob(**base)


# ── senior titles are always dropped ──────────────────────────────────
@pytest.mark.parametrize(
    "title",
    [
        "Senior Software Engineer",
        "Sr. Backend Developer",
        "Staff Engineer",
        "Principal Engineer",
        "Engineering Manager",
        "Tech Lead",
        "Software Architect",
        "Director of Engineering",
        "Head of Platform",
        "Software Engineer III",
    ],
)
def test_senior_titles_dropped(title):
    assert is_fresher_friendly(title, "great opportunity") is False


def test_entry_titles_kept():
    assert is_fresher_friendly("Software Engineer", "") is True
    assert is_fresher_friendly("Software Engineer II", "") is True  # II is ambiguous → kept
    assert is_fresher_friendly("Graduate Software Engineer", "") is True


# ── explicit entry signals win over a stray years number ──────────────
def test_entry_signal_overrides_years():
    desc = "New grad role. 5+ years of experience preferred but not required."
    assert is_fresher_friendly("Software Engineer", desc) is True


@pytest.mark.parametrize(
    "desc",
    [
        "This is an internship for summer 2026.",
        "Entry-level position, no prior experience required.",
        "We welcome freshers and new graduates.",
        "Graduate trainee program for campus hires.",
    ],
)
def test_entry_signals_kept(desc):
    assert is_fresher_friendly("Software Developer", desc) is True


# ── years gate ────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "desc",
    [
        "Requires 5+ years of professional experience.",
        "3-5 years of experience in backend systems.",
        "Minimum 4 years experience with distributed systems.",
        "8+ yrs building large-scale services.",
    ],
)
def test_experienced_roles_dropped(desc):
    assert is_fresher_friendly("Software Engineer", desc) is False


@pytest.mark.parametrize(
    "desc",
    [
        "0-2 years of experience.",
        "1-2 years experience preferred.",
        "Looking for someone with 2+ years or equivalent internships.",
        "No specific experience requirement listed here.",
    ],
)
def test_entry_or_lowyears_kept(desc):
    assert is_fresher_friendly("Software Engineer", desc) is True


def test_unstated_experience_kept():
    assert is_fresher_friendly("Backend Developer", "Build cool APIs with us.") is True


# ── min_required_years parser ─────────────────────────────────────────
def test_min_required_years_parser():
    assert min_required_years("5+ years") == 5
    assert min_required_years("3-5 years") == 3
    assert min_required_years("minimum 4 years") == 4
    assert min_required_years("0-2 years") == 0
    assert min_required_years("2+ years and 6+ years preferred") == 2  # min wins
    assert min_required_years("no numbers here") is None


# ── toggle + partition ────────────────────────────────────────────────
def test_disabled_keeps_everything(monkeypatch):
    # The toggle lives in keep_rawjob (is_fresher_friendly is the pure decision).
    monkeypatch.setattr(ef.settings, "experience_filter_enabled", False)
    senior = _job("Senior Staff Principal Engineer", "10+ years")
    assert keep_rawjob(senior) is True


def test_filter_rawjobs_partitions():
    jobs = [
        _job("Software Engineer", "Join our new grad cohort."),       # keep (entry)
        _job("Senior Software Engineer", "Lead a team."),             # drop (title)
        _job("Backend Developer", "Requires 6+ years experience."),   # drop (years)
        _job("Software Engineer", "Build APIs, 0-2 years."),          # keep (low years)
        _job("Software Engineer", ""),                                # keep (unstated)
    ]
    kept, dropped = filter_rawjobs(jobs)
    assert len(kept) == 3
    assert dropped == 2
