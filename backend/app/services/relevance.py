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
