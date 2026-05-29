"""
Provider routing + fallback tests.

We don't make real network calls — we monkey-patch each provider's
`_do_complete` so the test is deterministic and offline.
"""

from __future__ import annotations

import os

os.environ.setdefault("GEMINI_API_KEY", "test-key")
os.environ.setdefault("GROQ_API_KEY", "test-key")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import pytest

from app.services import llm as llm_mod


def _build_client(primary: str, fallback: str | None) -> llm_mod.LLMClient:
    """Build an LLMClient with primary/fallback overridden in-process.

    We avoid touching the real providers' __init__ (which would need network
    creds) by stubbing them on the LLMClient instance after construction.
    """
    client = llm_mod.LLMClient()
    client.primary_name = primary
    client.fallback_name = fallback
    client._primary = None
    client._fallback = None
    return client


class _FakeProvider(llm_mod.BaseProvider):
    """A controllable provider used in tests."""

    def __init__(self, name: str, behaviour: str, payload: str = "ok"):
        self.name = name
        self.calls = 0
        self.behaviour = behaviour  # "ok" | "fail"
        self.payload = payload

    def _do_complete(self, system, user, max_tokens, json_mode):
        self.calls += 1
        if self.behaviour == "fail":
            raise RuntimeError(f"{self.name} forced failure")
        return self.payload


def test_primary_succeeds_no_fallback_call():
    client = _build_client("gemini", "groq")
    client._primary = _FakeProvider("gemini", "ok", payload="hello-from-gemini")
    fake_fb = _FakeProvider("groq", "ok", payload="hello-from-groq")
    client._fallback = fake_fb

    out = client.complete("sys", "user")
    assert out == "hello-from-gemini"
    assert fake_fb.calls == 0  # fallback never touched


def test_failover_to_secondary_when_primary_raises():
    client = _build_client("gemini", "groq")
    bad_primary = _FakeProvider("gemini", "fail")
    good_fb = _FakeProvider("groq", "ok", payload="hello-from-groq")
    client._primary = bad_primary
    client._fallback = good_fb

    out = client.complete("sys", "user")
    assert out == "hello-from-groq"
    # Primary attempted (with tenacity retry — 2 attempts), then fallback.
    assert bad_primary.calls == 2
    assert good_fb.calls == 1


def test_both_providers_failing_raises():
    client = _build_client("gemini", "groq")
    client._primary = _FakeProvider("gemini", "fail")
    client._fallback = _FakeProvider("groq", "fail")

    with pytest.raises(RuntimeError):
        client.complete("sys", "user")


def test_no_fallback_configured_propagates_error():
    client = _build_client("gemini", None)
    client._primary = _FakeProvider("gemini", "fail")
    client._fallback = None  # explicitly none
    with pytest.raises(RuntimeError):
        client.complete("sys", "user")


def test_unknown_provider_name_raises():
    client = _build_client("does-not-exist", None)
    client._primary = None  # force lazy build via _build()
    with pytest.raises(ValueError):
        client.complete("sys", "user")


def test_complete_json_uses_provider_json_mode_flag():
    """complete_json should set json_mode=True on the provider call."""
    client = _build_client("gemini", None)

    captured = {}

    class _Capture(llm_mod.BaseProvider):
        name = "gemini"

        def _do_complete(self, system, user, max_tokens, json_mode):
            captured["json_mode"] = json_mode
            return '{"ok": true}'

    client._primary = _Capture()
    parsed = client.complete_json("sys", "user")
    assert parsed == {"ok": True}
    assert captured["json_mode"] is True
