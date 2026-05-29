"""
Experience gate — keep only fresher / entry-level roles.

The candidate is a final-year student with ~0 years of professional experience
(internships only). The single biggest source of irrelevant results was roles
that quietly require prior experience ("5+ years", "Senior", "Staff", "Lead",
"Manager", …). This gate drops those *before* a job is persisted or ranked, so
we neither store noise nor burn scarce free-tier LLM quota on jobs the candidate
can't realistically land.

Decision order on a freshly fetched RawJob (title + description):

  1. SENIOR TITLE  → drop. A "Senior/Staff/Principal/Lead/Manager/…/Engineer III"
     title is never a fresher role. (Scanned in the *title* only, so phrases like
     "work with senior engineers" in the body don't cause false drops.)
  2. ENTRY SIGNAL  → keep. Explicit "intern / new grad / entry-level / fresher /
     graduate program / trainee / no experience required" wins outright.
  3. YEARS GATE    → drop if the minimum required years stated anywhere exceeds
     MAX_EXPERIENCE_YEARS (default 2). "3+ years", "3-5 years", "minimum 4 years"
     → dropped; "0-2 years", "1-2 years" → kept.
  4. OTHERWISE     → keep. Roles that don't state experience are kept (most
     new-grad-friendly SWE postings don't list a number).

Deliberately simple/heuristic and biased toward *keeping* ambiguous roles — the
LLM ranker is the second line of defence (it's told to score senior / high-YOE
roles very low for this candidate).
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple, TYPE_CHECKING

from app.config import settings

if TYPE_CHECKING:  # avoid import cycle at runtime
    from app.sources.base import RawJob


# Seniority signals matched against the TITLE only (word-boundary, case-insens).
# "lead/architect/manager/director/head/vp" cover IC-senior + management ladders;
# roman numerals III+ cover the "Engineer III/IV/V" mid-senior levels (II is left
# out as too ambiguous — many "Engineer II" roles are still early-career).
_SENIOR_TITLE_RE = re.compile(
    r"\b(?:senior|sr\.?|staff|principal|lead|architect|manager|mgr|"
    r"director|head|vp|vice\s+president|distinguished|fellow)\b"
    r"|\b(?:iii|iv|v|vi|vii)\b",
    re.IGNORECASE,
)

# Explicit entry-level signals (matched in title + description head).
_ENTRY_SIGNAL_RE = re.compile(
    r"\b(?:"
    r"intern(?:ship)?|"
    r"new[\s-]?grad(?:uate)?|"
    r"graduate\s+(?:program|programme|trainee|scheme|engineer|developer)|"
    r"entry[\s-]?level|"
    r"fresher|freshers|"
    r"campus\s+hire|"
    r"trainee|"
    r"early[\s-]?career|"
    r"no\s+(?:prior\s+)?experience(?:\s+(?:required|needed))?"
    r")\b",
    re.IGNORECASE,
)

# A "<n> [+|-<m>] years/yrs" mention; group(1) is always the FLOOR of the range
# ("3-5 years" -> 3, "5+ years" -> 5, "minimum 3 years" -> 3, "0-2 years" -> 0).
_YEARS_RE = re.compile(
    r"(\d{1,2})\s*(?:\+|\s*[-–—]\s*\d{1,2})?\s*\+?\s*(?:years?|yrs?)\b",
    re.IGNORECASE,
)


def _has_senior_title(title: str) -> bool:
    return bool(_SENIOR_TITLE_RE.search(title or ""))


def _has_entry_signal(text: str) -> bool:
    return bool(_ENTRY_SIGNAL_RE.search(text or ""))


def min_required_years(text: str) -> Optional[int]:
    """Smallest stated years-of-experience floor, or None if none mentioned.

    We take the MIN across all mentions because the smallest "X+ years" is
    usually the hard requirement (larger numbers tend to be 'preferred')."""
    floors = [int(m.group(1)) for m in _YEARS_RE.finditer(text or "")]
    return min(floors) if floors else None


def is_fresher_friendly(title: str, description: str) -> bool:
    """Core decision, exposed for unit testing without a RawJob."""
    title = title or ""
    description = description or ""
    head = description[:1500]

    # 1. Senior title → never a fresher role.
    if _has_senior_title(title):
        return False

    # 2. Explicit entry-level signal wins.
    if _has_entry_signal(title) or _has_entry_signal(head):
        return True

    # 3. Years gate — drop if the stated minimum exceeds the cap.
    yrs = min_required_years(f"{title}\n{description}")
    if yrs is not None and yrs > settings.max_experience_years:
        return False

    # 4. Unstated / within cap → keep.
    return True


def keep_rawjob(raw: "RawJob") -> bool:
    """Decide whether a freshly fetched posting passes the experience gate."""
    if not settings.experience_filter_enabled:
        return True
    return is_fresher_friendly(raw.title or "", raw.description or "")


def filter_rawjobs(raws) -> Tuple[List["RawJob"], int]:
    """Apply the gate to an iterable, returning (kept_list, dropped_count)."""
    kept: List["RawJob"] = []
    dropped = 0
    for r in raws:
        if keep_rawjob(r):
            kept.append(r)
        else:
            dropped += 1
    return kept, dropped
