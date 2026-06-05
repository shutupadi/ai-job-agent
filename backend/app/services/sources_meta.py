"""
Per-source metadata: confidence + adapter health info.

Single source of truth for (a) the source-confidence ranking signal and (b) the
admin source dashboard (real-vs-stub, required credentials, kind).

Confidence reflects how trustworthy/complete a posting from that source tends to
be — direct ATS/company portals are authoritative; aggregators are decent;
public scrapes are weakest. It is a SMALL ranking nudge, never a substitute for
role fit.
"""

from __future__ import annotations

from app.config import settings

# kind: ats (direct company ATS) | aggregator | discovery
# confidence: high | medium | low
# required: env/setting attribute names that must be non-empty for the adapter to
#           actually return data (used by admin to flag "missing credentials").
# stub: True = adapter is a placeholder that returns nothing yet.
META: dict[str, dict] = {
    "greenhouse":      {"confidence": "high",   "kind": "ats",        "required": ["greenhouse_boards_raw"], "stub": False},
    "lever":           {"confidence": "high",   "kind": "ats",        "required": ["lever_companies_raw"],    "stub": False},
    "ashby":           {"confidence": "high",   "kind": "ats",        "required": ["ashby_boards_raw"],       "stub": False},
    "smartrecruiters": {"confidence": "high",   "kind": "ats",        "required": ["smartrecruiters_companies_raw"], "stub": False},
    "workday":         {"confidence": "high",   "kind": "ats",        "required": ["workday_tenants_raw"],    "stub": False},
    "oracle":          {"confidence": "high",   "kind": "ats",        "required": ["oracle_tenants_raw"],     "stub": False},
    "ycombinator":     {"confidence": "high",   "kind": "ats",        "required": [],                         "stub": False},
    "adzuna":          {"confidence": "medium", "kind": "aggregator", "required": ["adzuna_app_id", "adzuna_app_key"], "stub": False},
    "linkedin":        {"confidence": "low",    "kind": "discovery",  "required": [],                         "stub": False},
    "naukri":          {"confidence": "low",    "kind": "discovery",  "required": [],                         "stub": False},
    "indeed":          {"confidence": "low",    "kind": "discovery",  "required": [],                         "stub": True},
    "wellfound":       {"confidence": "low",    "kind": "discovery",  "required": [],                         "stub": True},
}

_SCORE = {"high": 90, "medium": 65, "low": 40, "unknown": 20}


def confidence_label(source: str) -> str:
    return META.get((source or "").lower(), {}).get("confidence", "unknown")


def confidence_score(source: str) -> int:
    """0..100 trust score for the source (defaults low/unknown for scraped/stub)."""
    return _SCORE.get(confidence_label(source), _SCORE["unknown"])


def meta_for(source: str) -> dict:
    return META.get((source or "").lower(), {"confidence": "unknown", "kind": "unknown", "required": [], "stub": True})


def missing_credentials(source: str) -> list[str]:
    """Required settings that are empty for this source (admin diagnostics)."""
    out: list[str] = []
    for attr in meta_for(source).get("required", []):
        val = getattr(settings, attr, "")
        if not (str(val).strip() if val is not None else ""):
            out.append(attr.upper().removesuffix("_RAW"))
    return out
