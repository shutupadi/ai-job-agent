"""
Unit tests for the location gate (app.services.geo_filter).

The candidate only wants jobs that are (a) in India, (b) remote, or
(c) international on-site roles that explicitly offer visa sponsorship.
Everything else must be dropped *before* ranking to save LLM quota.

geo_filter reads the `settings` singleton at call time, so we flip the three
relevant flags on it via monkeypatch rather than rebuilding Settings.
"""

from __future__ import annotations

import pytest

from app.services import geo_filter
from app.sources.base import RawJob


def _job(location="", remote=False, description="", **kw) -> RawJob:
    return RawJob(
        source="test",
        external_id="x",
        url="https://example.com/job",
        title="Software Engineer",
        company="Acme",
        location=location,
        remote=remote,
        description=description,
        **kw,
    )


@pytest.fixture
def gate_on(monkeypatch):
    """Enable the gate with remote + international allowed (the .env default)."""
    monkeypatch.setattr(geo_filter.settings, "geo_filter_enabled", True)
    monkeypatch.setattr(geo_filter.settings, "include_remote", True)
    monkeypatch.setattr(geo_filter.settings, "include_international", True)


# ── India ────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "loc",
    ["Bengaluru, India", "Noida", "Gurugram, Haryana", "Hyderabad", "Remote - India"],
)
def test_india_locations_are_kept(gate_on, loc):
    assert geo_filter.keep_rawjob(_job(location=loc)) is True


# ── Remote ───────────────────────────────────────────────────────────
def test_remote_flag_is_kept(gate_on):
    assert geo_filter.keep_rawjob(_job(location="San Francisco, CA", remote=True)) is True


def test_remote_in_location_string_is_kept(gate_on):
    assert geo_filter.keep_rawjob(_job(location="Remote (US)")) is True


def test_remote_dropped_when_include_remote_false(gate_on, monkeypatch):
    monkeypatch.setattr(geo_filter.settings, "include_remote", False)
    # No sponsorship language → with remote disabled this US remote role drops.
    assert geo_filter.keep_rawjob(_job(location="Remote (US)")) is False


# ── International + sponsorship ──────────────────────────────────────
def test_international_with_sponsorship_is_kept(gate_on):
    job = _job(
        location="Berlin, Germany",
        description="We offer visa sponsorship and relocation assistance for this role.",
    )
    assert geo_filter.keep_rawjob(job) is True


def test_international_without_sponsorship_is_dropped(gate_on):
    job = _job(location="Austin, TX", description="Great team, on-site only.")
    assert geo_filter.keep_rawjob(job) is False


def test_explicit_no_sponsorship_overrides_positive(gate_on):
    # Negative phrasing must win even if positive tokens also appear.
    job = _job(
        location="London, UK",
        description="Visa sponsorship is not available for this position.",
    )
    assert geo_filter.keep_rawjob(job) is False


def test_international_sponsorship_dropped_when_flag_off(gate_on, monkeypatch):
    monkeypatch.setattr(geo_filter.settings, "include_international", False)
    job = _job(location="Berlin, Germany", description="We will sponsor your visa.")
    assert geo_filter.keep_rawjob(job) is False


# ── Master switch ────────────────────────────────────────────────────
def test_gate_disabled_keeps_everything(monkeypatch):
    monkeypatch.setattr(geo_filter.settings, "geo_filter_enabled", False)
    job = _job(location="Austin, TX", description="on-site only, no sponsorship")
    assert geo_filter.keep_rawjob(job) is True


# ── filter_rawjobs aggregate ─────────────────────────────────────────
def test_filter_rawjobs_partitions_and_counts(gate_on):
    raws = [
        _job(location="Bengaluru, India"),                 # keep (india)
        _job(location="Remote"),                            # keep (remote)
        _job(location="Paris, France",
             description="visa sponsorship available"),     # keep (sponsor)
        _job(location="Seattle, WA", description="on-site"),  # drop
        _job(location="Toronto, Canada", description="no sponsorship"),  # drop
    ]
    kept, dropped = geo_filter.filter_rawjobs(raws)
    assert len(kept) == 3
    assert dropped == 2
