"""
Unit tests for the AiCredits provider + assorted pure helpers added during the
review-workflow rework. No network/DB:
  - LLMClient._parse_json (raw / fenced / array / prose / invalid)
  - AiCreditsProvider._do_complete (parse, empty-content, HTTP error)
  - schemas._files_url (storage path -> /files URL)
  - Settings.active_llm_model
  - export._default_manual_only
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services import export as export_mod
from app.services import llm as llm_mod
from app.services.llm import AiCreditsProvider, LLMClient


# ── LLMClient._parse_json ─────────────────────────────────────────────
def test_parse_json_raw():
    assert LLMClient._parse_json('{"a": 1}') == {"a": 1}


def test_parse_json_fenced():
    assert LLMClient._parse_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_parse_json_array():
    assert LLMClient._parse_json("[1, 2, 3]") == [1, 2, 3]


def test_parse_json_embedded_in_prose():
    assert LLMClient._parse_json('Sure! {"a": 1} hope that helps') == {"a": 1}


def test_parse_json_invalid_raises():
    with pytest.raises(ValueError):
        LLMClient._parse_json("no json here at all")


# ── AiCreditsProvider (fake HTTP client; no network) ──────────────────
class _Resp:
    def __init__(self, status, payload=None, text=""):
        self.status_code = status
        self._payload = payload
        self.text = text

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, resp):
        self._resp = resp
        self.last_body = None

    def post(self, path, json=None):
        self.last_body = json
        return self._resp


def _provider(monkeypatch, resp) -> AiCreditsProvider:
    monkeypatch.setattr(llm_mod.settings, "aicredits_api_key", "k")
    monkeypatch.setattr(llm_mod.settings, "aicredits_base_url", "https://api.example/v1")
    monkeypatch.setattr(llm_mod.settings, "aicredits_model", "anthropic/claude-3-haiku")
    p = AiCreditsProvider()
    p._client = _FakeClient(resp)  # swap real httpx client for the fake
    return p


def test_aicredits_parses_content(monkeypatch):
    resp = _Resp(200, {"choices": [{"message": {"content": "  hello  "}}]})
    p = _provider(monkeypatch, resp)
    assert p._do_complete("sys", "user", 100, False) == "hello"
    assert p._client.last_body["model"] == "anthropic/claude-3-haiku"


def test_aicredits_empty_content_raises(monkeypatch):
    resp = _Resp(200, {"choices": [{"message": {"content": ""}, "finish_reason": "length"}]})
    p = _provider(monkeypatch, resp)
    with pytest.raises(RuntimeError, match="empty content"):
        p._do_complete("sys", "user", 100, False)


def test_aicredits_http_error_raises(monkeypatch):
    resp = _Resp(429, payload=None, text="rate limited")
    p = _provider(monkeypatch, resp)
    with pytest.raises(RuntimeError, match="HTTP 429"):
        p._do_complete("sys", "user", 100, False)


# ── schemas._files_url ────────────────────────────────────────────────
def test_files_url_maps_storage_path():
    from app.config import settings
    from app.schemas.schemas import _files_url

    p = str(Path(settings.storage_dir) / "resumes" / "acme_1234.pdf")
    assert _files_url(p) == "/files/resumes/acme_1234.pdf"


def test_files_url_none_and_outside():
    from app.schemas.schemas import _files_url

    assert _files_url(None) is None
    assert _files_url("/definitely/not/under/storage.pdf") is None


# ── Settings.active_llm_model ─────────────────────────────────────────
def test_active_llm_model(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "llm_provider", "aicredits")
    monkeypatch.setattr(settings, "aicredits_model", "anthropic/claude-3-haiku")
    assert settings.active_llm_model == "anthropic/claude-3-haiku"

    monkeypatch.setattr(settings, "llm_provider", "groq")
    monkeypatch.setattr(settings, "groq_model", "llama-3.3-70b-versatile")
    assert settings.active_llm_model == "llama-3.3-70b-versatile"


# ── export._default_manual_only ───────────────────────────────────────
def test_default_manual_only_tracks_apply_mode(monkeypatch):
    monkeypatch.setattr(export_mod.settings, "apply_mode", "auto")
    assert export_mod._default_manual_only() is True
    monkeypatch.setattr(export_mod.settings, "apply_mode", "approval")
    assert export_mod._default_manual_only() is False
