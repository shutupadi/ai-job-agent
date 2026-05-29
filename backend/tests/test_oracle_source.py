"""
Unit tests for the Oracle Recruiting Cloud adapter (app.sources.oracle).

No network: we exercise the pure entry-parser and the dict->RawJob converter
(with the JD detail fetch monkeypatched out), using a payload shaped like the
real recruitingCEJobRequisitions response.
"""

from __future__ import annotations

from app.sources import oracle
from app.sources.oracle import OracleSource, _parse_entry


# ── _parse_entry ─────────────────────────────────────────────────────
def test_parse_entry_two_parts():
    assert _parse_entry("jpmc.fa.oraclecloud.com|CX_1001") == (
        "jpmc.fa.oraclecloud.com",
        "CX_1001",
        None,
    )


def test_parse_entry_with_display_name():
    assert _parse_entry("jpmc.fa.oraclecloud.com|CX_1001|JPMorgan Chase") == (
        "jpmc.fa.oraclecloud.com",
        "CX_1001",
        "JPMorgan Chase",
    )


def test_parse_entry_malformed_returns_none():
    assert _parse_entry("jpmc.fa.oraclecloud.com") is None
    assert _parse_entry("|CX_1001") is None
    assert _parse_entry("") is None


# ── _convert ─────────────────────────────────────────────────────────
def _job(**over):
    base = {
        "Id": "210736630",
        "Title": "Backend Software Engineer",
        "PostedDate": "2026-05-29",
        "PrimaryLocation": "Bengaluru, Karnataka, India",
        "PrimaryLocationCountry": "IN",
        "ShortDescriptionStr": "<p>Build APIs.</p>",
        "WorkplaceTypeCode": "ORA_ONSITE",
        "secondaryLocations": [],
    }
    base.update(over)
    return base


def test_convert_builds_rawjob(monkeypatch):
    src = OracleSource(tenants=[])
    monkeypatch.setattr(src, "_fetch_description", lambda *a, **k: "Full JD here.")
    raw = src._convert(None, "jpmc.fa.oraclecloud.com", "CX_1001", "JPMorgan Chase", _job())
    assert raw is not None
    assert raw.source == "oracle"
    assert raw.external_id == "210736630"
    assert raw.company == "JPMorgan Chase"
    assert raw.title == "Backend Software Engineer"
    assert raw.location == "Bengaluru, Karnataka, India"
    assert raw.description == "Full JD here."
    assert raw.auto_apply is True
    assert (
        raw.url
        == "https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/job/210736630"
    )


def test_convert_detects_remote_workplace(monkeypatch):
    src = OracleSource(tenants=[])
    monkeypatch.setattr(src, "_fetch_description", lambda *a, **k: "")
    raw = src._convert(
        None, "host.fa.oraclecloud.com", "CX_1", "Acme",
        _job(WorkplaceTypeCode="ORA_REMOTE", ShortDescriptionStr="Work anywhere."),
    )
    assert raw.remote is True


def test_convert_joins_secondary_locations(monkeypatch):
    src = OracleSource(tenants=[])
    monkeypatch.setattr(src, "_fetch_description", lambda *a, **k: "")
    raw = src._convert(
        None, "h", "CX_1", "Acme",
        _job(
            PrimaryLocation="New York, USA",
            secondaryLocations=[{"Name": "London, UK"}, {"Name": "Singapore"}],
        ),
    )
    assert raw.location == "New York, USA, London, UK, Singapore"


def test_convert_skips_when_missing_id_or_title(monkeypatch):
    src = OracleSource(tenants=[])
    monkeypatch.setattr(src, "_fetch_description", lambda *a, **k: "")
    assert src._convert(None, "h", "CX_1", "Acme", _job(Id="")) is None
    assert src._convert(None, "h", "CX_1", "Acme", _job(Title="")) is None


def test_list_url_shape():
    src = OracleSource(tenants=[])
    url = src._list_url("jpmc.fa.oraclecloud.com", "CX_1001", 25, 50, "software engineer")
    assert "recruitingCEJobRequisitions" in url
    assert "siteNumber=CX_1001" in url
    assert "limit=25" in url
    assert "offset=50" in url
    assert "keyword=software%20engineer" in url
