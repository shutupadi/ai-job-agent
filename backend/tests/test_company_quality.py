"""Unit tests for the company-quality database (app.services.company_quality)."""

from __future__ import annotations

from app.services import company_quality as cq


def test_normalize_strips_suffixes_and_punct():
    assert cq.normalize("Stripe, Inc.") == "stripe"
    assert cq.normalize("Acme Technologies Pvt Ltd") == "acme"


def test_static_tiers():
    assert cq.tier_for("Google") == 1
    assert cq.tier_for("Amazon Web Services") == 1   # substring → amazon
    assert cq.tier_for("Adobe") == 2
    assert cq.tier_for("Razorpay") == 3
    assert cq.tier_for("Some Random Co") == 4         # unknown → neutral


def test_admin_override_wins():
    overrides = cq.seed_overrides([(1, ["Some Random Co"])])
    assert cq.tier_for("Some Random Co", overrides) == 1


def test_suspicious_detection():
    assert cq.tier_for("ABC Staffing Consultancy") == 5
    assert cq.is_suspicious("XYZ Consultancy", "Hiring", "") is True
    assert cq.is_suspicious(
        "Real Co", "Data Entry", "registration fee required to start"
    ) is True
    assert cq.is_suspicious("Stripe", "Backend Engineer", "Build APIs") is False


def test_tier_score_monotonic():
    assert cq.tier_score(1) > cq.tier_score(2) > cq.tier_score(3) > cq.tier_score(4) > cq.tier_score(5)
