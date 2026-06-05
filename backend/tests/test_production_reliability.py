"""
Production-reliability unit tests:
  - shared job pool no longer drops senior jobs globally
  - fresher vs experienced per-user filtering
  - source confidence affects ranking
  - production email-verification safety (no fake auto-verify)
  - encoding cleanliness smoke test
"""

from __future__ import annotations

import contextlib
from pathlib import Path

import pytest

from app.services import experience_filter as ef
from app.services import otp, pipeline, scoring, sources_meta
from app.services.scoring import UserCtx
from app.sources.base import RawJob


@pytest.fixture(autouse=True)
def _cfg(monkeypatch):
    monkeypatch.setattr(ef.settings, "experience_filter_enabled", True)
    monkeypatch.setattr(ef.settings, "max_experience_years", 2)


# ── Task 1: shared pool keeps ALL levels (no global experience drop) ──
def test_shared_pool_keeps_senior_jobs(monkeypatch):
    senior = RawJob(source="greenhouse", external_id="s", url="https://x/s",
                    title="Senior Staff Engineer", company="Acme",
                    description="10+ years required", location="Remote")
    entry = RawJob(source="greenhouse", external_id="e", url="https://x/e",
                   title="Software Engineer", company="Acme",
                   description="new grad welcome", location="Remote")

    monkeypatch.setattr(pipeline, "_fetch_all", lambda: ([senior, entry], {}))
    monkeypatch.setattr(pipeline.source_health, "record", lambda stats: None)
    captured: dict = {}

    def fake_upsert(db, kept):
        captured["kept"] = list(kept)
        return [], 0

    monkeypatch.setattr(pipeline, "upsert_jobs", fake_upsert)

    class _Run:
        jobs_found = 0
        jobs_new = 0

    @contextlib.contextmanager
    def fake_scope():
        class _DB:
            def get(self, *a):
                return _Run()
        yield _DB()

    monkeypatch.setattr(pipeline, "session_scope", fake_scope)
    pipeline._do_fetch("run1", [])

    titles = [r.title for r in captured["kept"]]
    assert "Senior Staff Engineer" in titles  # NOT dropped at ingestion
    assert "Software Engineer" in titles


def test_watchlist_fetch_ingests_only_watchlist_companies(monkeypatch):
    stripe = RawJob(source="greenhouse", external_id="s", url="https://x/s",
                    title="Backend Engineer", company="Stripe",
                    description="apis", location="Remote")
    other = RawJob(source="greenhouse", external_id="o", url="https://x/o",
                   title="Backend Engineer", company="RandomCo",
                   description="apis", location="Remote")
    monkeypatch.setattr(pipeline, "_fetch_all", lambda: ([stripe, other], {}))
    monkeypatch.setattr(pipeline.source_health, "record", lambda stats: None)
    captured: dict = {}

    def fake_upsert(db, kept):
        captured["kept"] = list(kept)
        return [], 0

    monkeypatch.setattr(pipeline, "upsert_jobs", fake_upsert)

    class _Run:
        jobs_found = 0
        jobs_new = 0

    @contextlib.contextmanager
    def fake_scope():
        class _DB:
            def get(self, *a):
                return _Run()
        yield _DB()

    monkeypatch.setattr(pipeline, "session_scope", fake_scope)
    pipeline._do_fetch("run1", [], company_filter={"stripe"})
    companies = [r.company for r in captured["kept"]]
    assert companies == ["Stripe"]  # only watchlist company ingested


def test_fresher_user_does_not_see_senior():
    assert pipeline.passes_prefilter(True, 0, True, "Senior Staff Engineer", "10+ years") is False


def test_experienced_user_can_see_senior():
    assert pipeline.passes_prefilter(True, 7, False, "Senior Staff Engineer", "build systems") is True


# ── Task 3: source confidence affects ranking ──
def _ctx() -> UserCtx:
    return UserCtx(years=3, technical=True, skills={"python"}, terms={"python"},
                   target_titles=["Backend Engineer"])


def test_source_confidence_changes_score():
    common = dict(title="Backend Engineer", company="Acme",
                  description="Python work. " * 30, ats_keywords=["Python"],
                  llm_overall=70, llm_breakdown={"ats_match": 70, "shortlist_likelihood": 70})
    high = scoring.score_job(_ctx(), source="greenhouse", **common)
    low = scoring.score_job(_ctx(), source="linkedin", **common)
    assert high["score"] > low["score"]
    assert high["signals"]["source_confidence"] == "high"
    assert low["signals"]["source_confidence"] == "low"


def test_sources_meta_confidence_tiers():
    assert sources_meta.confidence_label("greenhouse") == "high"
    assert sources_meta.confidence_label("adzuna") == "medium"
    assert sources_meta.confidence_label("linkedin") == "low"
    assert sources_meta.confidence_label("indeed") == "low"
    assert sources_meta.meta_for("indeed")["stub"] is True
    assert sources_meta.meta_for("greenhouse")["stub"] is False


# ── Task 7: production email-verification safety ──
def test_prod_verification_not_faked(monkeypatch):
    monkeypatch.setattr(otp.settings, "require_email_verification", True)
    monkeypatch.setattr(otp.settings, "app_env", "prod")
    monkeypatch.setattr(otp.settings, "email_provider", "")  # no provider
    # Must STILL enforce (never silently auto-verify) ...
    assert otp.verification_active() is True
    # ... and flag the misconfiguration loudly.
    assert otp.email_misconfigured() is True


def test_verification_off_when_disabled(monkeypatch):
    monkeypatch.setattr(otp.settings, "require_email_verification", False)
    assert otp.verification_active() is False
    assert otp.email_misconfigured() is False


# ── Task 6: encoding cleanliness smoke test ──
def test_no_mojibake_in_source():
    root = Path(__file__).resolve().parents[2]
    bad = ("Ã", "â€", "Â\xa0", "�")
    offenders = []
    for base, exts in ((root / "backend" / "app", {".py", ".txt"}),
                       (root / "frontend" / "src", {".ts", ".tsx"})):
        for p in base.rglob("*"):
            if p.suffix in exts:
                text = p.read_text(encoding="utf-8", errors="replace")
                if any(b in text for b in bad):
                    offenders.append(str(p))
    assert offenders == [], f"Mojibake found in: {offenders}"
