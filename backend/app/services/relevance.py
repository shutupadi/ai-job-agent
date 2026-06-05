"""
Cheap, deterministic résumé↔job relevance scoring (no LLM, no embeddings).

Used to PRE-SELECT which jobs are worth spending an LLM rank call on: instead of
ranking the newest N jobs (which may be sales/HR/etc.), we rank the N jobs whose
title + description best overlap the candidate's actual skills and role. This is
the single biggest relevance lever — the LLM then only ever sees on-target jobs.
"""

from __future__ import annotations

import re
from typing import Set

_WORD = re.compile(r"[a-zA-Z][a-zA-Z+#.]{1,}")

_STOP = {
    "and", "or", "the", "for", "with", "from", "you", "your", "our", "their",
    "will", "are", "was", "have", "has", "had", "this", "that", "these", "those",
    "all", "any", "can", "may", "use", "using", "used", "work", "working", "team",
    "teams", "role", "roles", "job", "jobs", "year", "years", "experience", "etc",
    "new", "build", "building", "across", "into", "via", "per", "end", "also",
    "strong", "good", "great", "best", "looking", "join", "help", "ability",
}

# Markers that the candidate is in a technical / engineering field.
_TECH_MARKERS = {
    "python", "java", "javascript", "typescript", "c++", "c#", "go", "golang",
    "rust", "kotlin", "scala", "sql", "react", "node", "node.js", "spring",
    "django", "fastapi", "kubernetes", "docker", "aws", "gcp", "azure", "kafka",
    "spark", "tensorflow", "pytorch", "ml", "machine", "backend", "frontend",
    "devops", "microservices", "distributed", "algorithms", "data",
}

# Title tokens that signal an engineering/tech/quant role (good for tech CVs).
_TECH_TITLE = {
    "engineer", "engineering", "developer", "sde", "swe", "programmer",
    "architect", "backend", "frontend", "full-stack", "fullstack", "devops",
    "sre", "reliability", "platform", "systems", "infrastructure", "cloud",
    "security", "data", "ml", "machine", "scientist", "quant", "software",
    "analyst", "android", "ios", "mobile", "qa", "test",
}

# Title tokens that signal a NON-technical profession (bad for a tech CV).
_NONTECH_TITLE = {
    "sales", "account", "recruiter", "recruiting", "talent", "marketing",
    "customer", "support", "success", "business development", "hr", "human",
    "people", "accountant", "finance", "office", "administrative", "receptionist",
    "partner", "go-to-market", "communications", "content", "designer", "design",
    "legal", "counsel", "operations manager", "procurement",
}

# Title phrases that are ALWAYS the wrong profession for a technical candidate —
# used for a HARD pre-filter drop (not just a score penalty), so we never spend
# an LLM call on, e.g., a "Sales Engineer" or "Technical Recruiter" for a SWE.
# Word-boundary matched against the title. Kept tight to avoid false drops:
# borderline-technical titles (solutions/systems/data) are deliberately absent.
_WRONG_DIRECTION_RE = re.compile(
    r"\b("
    r"sales|account\s+executive|account\s+manager|business\s+development|"
    r"recruit(?:er|ing)|talent\s+acquisition|sourcer|"
    r"marketing|brand|seo|social\s+media|copywriter|"
    r"customer\s+success|customer\s+support|"
    r"human\s+resources|hr\s+(?:manager|generalist|business)|"
    r"accountant|bookkeeper|payroll|receptionist|"
    r"paralegal|attorney|counsel|"
    r"nurse|teacher|driver|warehouse|cashier|barista|"
    r"executive\s+assistant|administrative\s+assistant|office\s+manager"
    r")\b",
    re.IGNORECASE,
)

# Resume hints that the candidate is heading in a technical direction.
_ROLE_DIRECTION_TECH = {
    "software", "engineering", "engineer", "developer", "backend", "frontend",
    "full-stack", "fullstack", "data", "machine learning", "ml", "ai",
    "devops", "sre", "platform", "security", "quant", "android", "ios", "mobile",
}


def _words(text: str) -> Set[str]:
    return {
        w.lower()
        for w in _WORD.findall(text or "")
        if len(w) > 2 and w.lower() not in _STOP
    }


def candidate_terms(resume_json: dict) -> Set[str]:
    """The candidate's distinctive skill/role terms (lowercased)."""
    terms: Set[str] = set()
    skills = resume_json.get("skills") or {}
    if isinstance(skills, dict):
        for v in skills.values():
            for s in (v or []):
                terms.add(str(s).lower().strip())
    elif isinstance(skills, list):
        for s in skills:
            terms.add(str(s).lower().strip())
    for e in (resume_json.get("experience") or []):
        if isinstance(e, dict) and e.get("title"):
            terms |= _words(str(e["title"]))
    terms |= _words(resume_json.get("summary") or "")
    return {t for t in terms if t and t not in _STOP}


def is_technical(terms: Set[str]) -> bool:
    return len(terms & _TECH_MARKERS) >= 2


def role_is_technical(resume_json: dict, terms: Set[str] | None = None) -> bool:
    """Whether the candidate is on a technical track. Reads the parser's explicit
    `role_direction` / `target_titles` first (most reliable), then falls back to
    skill-marker overlap. Robust to older résumés parsed before those fields."""
    direction = str(resume_json.get("role_direction") or "").lower()
    if direction:
        if any(tok in direction for tok in _ROLE_DIRECTION_TECH):
            return True
        # An explicit NON-tech direction overrides marker heuristics.
        if _WRONG_DIRECTION_RE.search(direction):
            return False
    targets = resume_json.get("target_titles") or []
    if isinstance(targets, list):
        joined = " ".join(str(t).lower() for t in targets)
        if any(p in joined for p in _TECH_TITLE):
            return True
    if terms is None:
        terms = candidate_terms(resume_json)
    return is_technical(terms)


def is_wrong_direction(technical: bool, title: str) -> bool:
    """True when a TECHNICAL candidate is looking at a clearly non-technical
    profession (sales / recruiting / marketing / HR / …). Used as a HARD drop in
    the pre-filter so off-profession roles never reach the LLM ranker."""
    if not technical:
        return False
    t = (title or "")
    if _WRONG_DIRECTION_RE.search(t):
        # A genuine engineering title (e.g. "Software Engineer, Sales Platform")
        # should survive — only drop when there's no real eng signal in the title.
        tl = t.lower()
        eng = {"software engineer", "backend", "frontend", "full-stack",
               "fullstack", "developer", "data engineer", "ml engineer",
               "machine learning", "devops", "sre"}
        if not any(e in tl for e in eng):
            return True
    return False


def relevance_score(terms: Set[str], technical: bool, title: str, desc: str) -> int:
    """Higher = more on-target for this candidate. Title overlap counts ~3x a
    description hit; the job's role direction nudges tech CVs toward tech roles
    and away from sales/HR/etc."""
    t = (title or "").lower()
    d = (desc or "")[:3000].lower()
    score = 0
    for term in terms:
        if not term:
            continue
        if term in t:
            score += 3
        elif term in d:
            score += 1
    if technical:
        if any(p in t for p in _TECH_TITLE):
            score += 5
        if any(n in t for n in _NONTECH_TITLE):
            score -= 10  # likely the wrong profession for a technical candidate
    return score
