"""
Internal company-quality database.

Tiers (1 = best) are a RANKING SIGNAL ONLY — never a substitute for role fit.
A Tier-1 company with a wrong-role posting must still rank low (enforced in
scoring.py). Static defaults live here; admins can override per-company via the
`company_tiers` table (see `tier_for`, which consults the DB first).

Tier 5 = "avoid" (spammy consultancies / training scams / commission-only).
Unknown companies default to Tier 4 (average) — neutral, not penalised.
"""

from __future__ import annotations

import re
from typing import Iterable, Optional

# ── Static seed tiers ────────────────────────────────────────────────
_TIER1 = {
    "google", "alphabet", "microsoft", "amazon", "aws", "apple", "meta",
    "facebook", "netflix", "nvidia", "goldman sachs", "jpmorgan", "jp morgan",
    "j.p. morgan", "morgan stanley", "bloomberg", "stripe", "databricks",
    "citadel", "jane street", "de shaw", "d. e. shaw", "tower research",
    "openai", "anthropic", "two sigma", "hudson river trading", "hrt",
}
_TIER2 = {
    "adobe", "oracle", "salesforce", "paypal", "atlassian", "uber", "airbnb",
    "coinbase", "intuit", "servicenow", "visa", "mastercard", "american express",
    "amex", "barclays", "citi", "citigroup", "bnp paribas", "linkedin", "snowflake",
    "datadog", "confluent", "mongodb", "cloudflare", "palantir", "roblox",
    "pinterest", "doordash", "instacart", "robinhood", "plaid", "brex", "ramp",
    "deutsche bank", "ubs", "hsbc", "wells fargo", "blackrock", "blackstone",
    "optiver", "jump trading", "millennium", "point72", "susquehanna", "sig",
}
_TIER3 = {
    # strong product/SaaS/fintech + well-funded startups (extend freely)
    "razorpay", "cred", "zerodha", "groww", "phonepe", "postman", "freshworks",
    "zoho", "swiggy", "zomato", "flipkart", "meesho", "notion", "figma", "canva",
    "scale ai", "hashicorp", "gitlab", "vercel", "supabase", "rippling",
    "navi", "perplexity", "zepto", "browserstack", "chargebee", "hasura",
}
# Patterns that strongly suggest a low-quality / risky posting or "company".
_SUSPICIOUS_NAME = re.compile(
    r"\b(consultanc(?:y|ies)|staffing|manpower|placements?|recruit(?:ment|ers?)\s+"
    r"(?:agency|services)|training\s+institute|academy|work\s+from\s+home\s+jobs?)\b",
    re.IGNORECASE,
)
_SUSPICIOUS_TEXT = re.compile(
    r"\b(registration\s+fee|pay\s+(?:a\s+)?fee|security\s+deposit|"
    r"earn\s+\$?\d+\s*(?:per\s+day|/day|daily)|commission[\s-]only|"
    r"unlimited\s+earning|be\s+your\s+own\s+boss|investment\s+required|"
    r"part[\s-]time\s+data\s+entry|no\s+experience\s+needed\s+earn)\b",
    re.IGNORECASE,
)

_NORM_RE = re.compile(r"[^a-z0-9 ]+")
_SUFFIX_RE = re.compile(
    r"\b(inc|llc|ltd|limited|pvt|private|corp|corporation|technologies|technology|"
    r"labs|software|solutions|systems|global|services|gmbh|sa|co)\b",
    re.IGNORECASE,
)


def normalize(name: Optional[str]) -> str:
    """Lowercased, punctuation/suffix-stripped key for matching."""
    s = (name or "").lower().strip()
    s = _NORM_RE.sub(" ", s)
    s = _SUFFIX_RE.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def _static_tier(norm: str) -> Optional[int]:
    if not norm:
        return None
    # Substring match so "amazon web services" → amazon (tier 1), etc.
    for tier, names in ((1, _TIER1), (2, _TIER2), (3, _TIER3)):
        if any(n in norm or norm in n for n in names):
            return tier
    return None


def tier_for(company: str, overrides: Optional[dict] = None) -> int:
    """Company tier 1..4 (5 = avoid). `overrides` is an optional {norm: tier} map
    loaded from the company_tiers table (admin edits win over the static seed)."""
    norm = normalize(company)
    if overrides and norm in overrides:
        return overrides[norm]
    if _SUSPICIOUS_NAME.search(company or ""):
        return 5
    static = _static_tier(norm)
    return static if static is not None else 4


def is_suspicious(company: str, title: str = "", description: str = "") -> bool:
    """True for likely scam / spam / commission-only postings."""
    if _SUSPICIOUS_NAME.search(company or ""):
        return True
    blob = f"{title}\n{description[:1500]}"
    return bool(_SUSPICIOUS_TEXT.search(blob))


def tier_score(tier: int) -> int:
    """0..100 company-quality sub-score for the hybrid ranker."""
    return {1: 100, 2: 85, 3: 70, 4: 50, 5: 0}.get(tier, 50)


def seed_overrides(names_by_tier: Iterable[tuple[int, Iterable[str]]]) -> dict:
    """Helper to build an overrides map (used by admin seeding/tests)."""
    out: dict = {}
    for tier, names in names_by_tier:
        for n in names:
            out[normalize(n)] = tier
    return out


# Default watchlist suggestions surfaced to new users (frontend may also hardcode).
DEFAULT_WATCHLIST = [
    "Google", "Microsoft", "Amazon", "Goldman Sachs", "Morgan Stanley",
    "JPMorgan", "Bloomberg", "Atlassian", "Stripe", "Databricks", "Oracle",
    "Salesforce", "Adobe", "PayPal", "Uber", "Nvidia", "Apple", "Meta",
    "Netflix", "Citadel", "Jane Street", "DE Shaw", "Tower Research",
]
