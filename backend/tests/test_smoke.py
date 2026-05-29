"""
Smoke tests that don't require a real DB or LLM API key.

We only test:
  - config loads
  - source dataclasses build
  - form-filler field-kind inference
  - PDF renderer writes a real file
  - LLM JSON parser handles fenced/unfenced JSON
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

os.environ.setdefault("GEMINI_API_KEY", "test-key")
os.environ.setdefault("GROQ_API_KEY", "test-key")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("LLM_PROVIDER", "gemini")
os.environ.setdefault("LLM_FALLBACK_PROVIDER", "groq")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")


def test_config_loads():
    from app.config import settings

    assert settings.app_env in ("dev", "prod", "test")
    assert isinstance(settings.keywords, list)


def test_rawjob_url_hash():
    from app.sources.base import RawJob

    r = RawJob(
        source="greenhouse",
        external_id="1",
        url="https://example.com/jobs/1",
        title="SDE",
        company="Example",
    )
    assert len(r.url_hash) == 64


def test_infer_field_kind():
    from app.automation.form_filler import infer_field_kind

    assert infer_field_kind("First Name") == "first_name"
    assert infer_field_kind("email") == "email"
    assert infer_field_kind("Notice Period") == "notice"
    assert infer_field_kind("Random Q") is None


def test_llm_json_parser_handles_fences():
    from app.services.llm import LLMClient

    assert LLMClient._parse_json('{"a": 1}') == {"a": 1}
    assert LLMClient._parse_json('```json\n{"a": 2}\n```') == {"a": 2}
    assert LLMClient._parse_json('garbage before {"a": 3} garbage after') == {"a": 3}


def test_render_resume_pdf():
    from app.services.pdf_renderer import render_resume_pdf

    resume = {
        "name": "Ada Lovelace",
        "email": "ada@example.com",
        "phone": "+91-9999999999",
        "links": {"github": "https://github.com/ada"},
        "summary": "Engineer.",
        "skills": {"languages": ["Python", "Java"]},
        "experience": [
            {
                "title": "SWE Intern",
                "company": "BabbageCo",
                "start": "2024",
                "end": "2025",
                "bullets": ["Did stuff."],
            }
        ],
    }
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "resume.pdf"
        render_resume_pdf(resume, out)
        assert out.exists() and out.stat().st_size > 1000
