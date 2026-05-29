"""
Location gate.

The user only wants to consider jobs that are:
  (a) located in India, OR
  (b) remote (when INCLUDE_REMOTE), OR
  (c) international on-site roles that explicitly offer visa sponsorship
      (when INCLUDE_INTERNATIONAL).

Everything else (e.g. an on-site San Francisco role with no sponsorship) is
dropped *before* it is persisted or ranked — this keeps the DB clean and,
more importantly, stops us from burning scarce free-tier LLM quota ranking
jobs the candidate can't realistically take.

The matching is deliberately simple/heuristic and operates on the location
string plus the first slice of the description. It errs toward keeping India
and remote roles, and is conservative about international ones.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from app.config import settings

if TYPE_CHECKING:  # avoid import cycle at runtime
    from app.sources.base import RawJob


# Indian cities, metros, states + the country itself. Lowercased; matched as
# substrings of the (lowercased) location string.
_INDIA_TOKENS = {
    # country
    "india", "bharat",
    # metros / tech hubs
    "noida", "gurgaon", "gurugram", "bengaluru", "bangalore", "hyderabad",
    "pune", "mumbai", "navi mumbai", "thane", "new delhi", "delhi", "chennai",
    "kolkata", "ahmedabad", "jaipur", "chandigarh", "mohali", "kochi", "cochin",
    "coimbatore", "indore", "nagpur", "thiruvananthapuram", "trivandrum",
    "mysore", "mysuru", "gandhinagar", "vadodara", "bhubaneswar",
    "visakhapatnam", "vizag", "faridabad", "ghaziabad", "lucknow", "surat",
    "nashik", "vijayawada", "mangalore", "mangaluru", "kanpur", "bhopal",
    # states / regions
    "karnataka", "maharashtra", "telangana", "tamil nadu", "uttar pradesh",
    "haryana", "gujarat", "west bengal", "kerala", "rajasthan", "punjab",
    "andhra pradesh", "madhya pradesh", "odisha", "delhi ncr", "ncr",
}

_SPONSOR_POSITIVE = re.compile(
    r"\b("
    r"visa sponsorship|sponsor(?:ship)? (?:is )?available|we (?:can |will )?sponsor|"
    r"sponsor your visa|relocation (?:assistance|support|package|provided)|"
    r"work (?:visa|permit) (?:support|sponsorship)|h-?1b|"
    r"willing to sponsor|sponsorship offered|visa support"
    r")\b",
    re.IGNORECASE,
)

_SPONSOR_NEGATIVE = re.compile(
    r"\b("
    r"no (?:visa )?sponsorship|not (?:able to |be able to )?sponsor|"
    r"cannot sponsor|can't sponsor|unable to sponsor|without sponsorship|"
    r"do(?:es)? not (?:offer|provide) sponsorship|sponsorship is not|"
    r"not (?:offer|provide) (?:visa )?sponsorship|no (?:visa )?support"
    r")\b",
    re.IGNORECASE,
)

_REMOTE_RE = re.compile(r"\bremote\b|work from home|\bwfh\b", re.IGNORECASE)


def _is_india(text: str) -> bool:
    t = (text or "").lower()
    if not t:
        return False
    return any(tok in t for tok in _INDIA_TOKENS)


def _mentions_remote(text: str) -> bool:
    return bool(_REMOTE_RE.search(text or ""))


def offers_sponsorship(description: str) -> bool:
    """True only if sponsorship is positively offered and not explicitly denied."""
    d = description or ""
    if _SPONSOR_NEGATIVE.search(d):
        return False
    return bool(_SPONSOR_POSITIVE.search(d))


def keep_rawjob(raw: "RawJob") -> bool:
    """Decide whether a freshly fetched posting passes the location gate."""
    if not settings.geo_filter_enabled:
        return True

    location = raw.location or ""
    head = (raw.description or "")[:400]  # only scan the top of the JD

    # (a) India-located
    if _is_india(location):
        return True

    # (b) Remote (any geography) — the candidate explicitly wants remote roles.
    if settings.include_remote and (raw.remote or _mentions_remote(location) or _mentions_remote(head)):
        return True

    # (c) International on-site, but only if visa sponsorship is on the table.
    if settings.include_international and offers_sponsorship(raw.description or ""):
        return True

    return False


def filter_rawjobs(raws):
    """Apply the gate to an iterable, returning (kept_list, dropped_count)."""
    kept = []
    dropped = 0
    for r in raws:
        if keep_rawjob(r):
            kept.append(r)
        else:
            dropped += 1
    return kept, dropped
