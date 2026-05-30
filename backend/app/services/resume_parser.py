"""
Extract text from an uploaded résumé (PDF / DOCX / TXT) and AI-parse it into the
structured master-résumé JSON used throughout the app.

No fabrication: the LLM is instructed to use only what's in the file. The result
is validated to contain the keys the resume engine / ranker rely on.
"""

from __future__ import annotations

import io

from app.services.llm import llm
from app.utils.logger import log

REQUIRED_KEYS = {"name", "email", "phone", "summary", "skills", "experience"}


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
    for k in ("experience", "projects", "education", "achievements"):
        if not isinstance(p.get(k), list):
            p[k] = []
    for k in ("name", "email", "phone", "summary"):
        if not isinstance(p.get(k), str):
            p[k] = str(p.get(k) or "")
    try:
        p["experience_years"] = max(0, int(float(p.get("experience_years") or 0)))
    except (TypeError, ValueError):
        p["experience_years"] = 0


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
