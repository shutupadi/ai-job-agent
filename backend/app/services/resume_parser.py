"""
Extract text from an uploaded résumé (PDF / DOCX / TXT) and AI-parse it into the
structured master-résumé JSON used throughout the app.

No fabrication: the LLM is instructed to use only what's in the file. The result
is validated to contain the keys the resume engine / ranker rely on.
"""

from __future__ import annotations

import datetime as dt
import io
import re

from app.services.llm import llm
from app.utils.logger import log

REQUIRED_KEYS = {"name", "email", "phone", "summary", "skills", "experience"}

_YEAR_RE = re.compile(r"(19|20)\d{2}")


def _estimate_years_from_experience(experience) -> int:
    """Deterministic fallback: total years spanned by experience entries' dates."""
    if not isinstance(experience, list):
        return 0
    now = dt.datetime.utcnow().year
    total = 0
    for e in experience:
        if not isinstance(e, dict):
            continue
        sm = _YEAR_RE.search(str(e.get("start") or ""))
        em = _YEAR_RE.search(str(e.get("end") or ""))
        start = int(sm.group()) if sm else None
        end = int(em.group()) if em else now
        if start:
            total += max(0, min(end, now) - start)
    return total


def _flat_skills(skills) -> list:
    out: list = []
    if isinstance(skills, dict):
        for v in skills.values():
            if isinstance(v, list):
                out.extend(str(s) for s in v if s)
    elif isinstance(skills, list):
        out = [str(s) for s in skills if s]
    return out


# ── text extraction ───────────────────────────────────────────────────
def _pdf_text(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _docx_text(data: bytes) -> str:
    import docx  # python-docx

    document = docx.Document(io.BytesIO(data))
    return "\n".join(p.text for p in document.paragraphs)


def extract_text(filename: str, data: bytes) -> str:
    name = (filename or "").lower()
    if name.endswith(".pdf"):
        return _pdf_text(data)
    if name.endswith(".docx"):
        return _docx_text(data)
    if name.endswith((".txt", ".md")):
        return data.decode("utf-8", errors="ignore")
    # Unknown extension — sniff: try PDF, then DOCX, then plain text.
    for fn in (_pdf_text, _docx_text):
        try:
            t = fn(data)
            if t.strip():
                return t
        except Exception:
            continue
    return data.decode("utf-8", errors="ignore")


# ── LLM parse ──────────────────────────────────────────────────────────
def _normalize(p: dict) -> None:
    p.setdefault("links", {})
    p.setdefault("skills", {})
    for k in ("experience", "projects", "education", "achievements",
              "target_titles", "target_job_types", "domains", "primary_skills"):
        if not isinstance(p.get(k), list):
            p[k] = []
    for k in ("name", "email", "phone", "summary", "role_direction", "seniority"):
        if not isinstance(p.get(k), str):
            p[k] = str(p.get(k) or "")

    # Years: trust the LLM, but never let it under-report below what the dated
    # experience entries imply (a common failure on senior résumés).
    try:
        llm_years = max(0, int(float(p.get("experience_years") or 0)))
    except (TypeError, ValueError):
        llm_years = 0
    p["experience_years"] = max(llm_years, _estimate_years_from_experience(p.get("experience")))

    # Seniority: derive deterministically if absent/invalid (keep LLM value only
    # when it's one of the three canonical bands).
    yrs = p["experience_years"]
    band = (p.get("seniority") or "").strip().lower()
    if band not in ("entry", "mid", "senior"):
        band = "entry" if yrs < 2 else "mid" if yrs < 6 else "senior"
    p["seniority"] = band

    # primary_skills fallback: top of the flattened skills list.
    if not p["primary_skills"]:
        p["primary_skills"] = _flat_skills(p.get("skills"))[:10]


def parse_resume_text(text: str) -> dict:
    text = (text or "").strip()
    if len(text) < 30:
        raise ValueError(
            "Couldn't read enough text from the résumé — if it's a scanned image, "
            "please upload a text-based PDF or DOCX."
        )
    prompt = llm.load_prompt("parse_resume").format(resume_text=text[:12000])
    parsed = llm.complete_json(
        system="You are a precise résumé parser. Output JSON only.",
        user=prompt,
        max_tokens=3000,
    )
    if not isinstance(parsed, dict):
        raise ValueError("Résumé parser did not return a JSON object.")
    _normalize(parsed)
    missing = REQUIRED_KEYS - set(parsed.keys())
    if missing:
        raise ValueError(f"Parsed résumé is missing fields: {sorted(missing)}")
    log.info(f"Parsed résumé for {parsed.get('name') or 'unknown'} ({len(text)} chars in)")
    return parsed


def extract_and_parse(filename: str, data: bytes) -> tuple[str, dict]:
    text = extract_text(filename, data)
    return text, parse_resume_text(text)
