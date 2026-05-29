"""
LLM facade with multi-provider support and automatic failover.

Providers (in priority order, set via env):
  - aicredits — AiCredits.in OpenAI-compatible gateway (paid, INR). One key,
                many models. Use a NON-thinking model (anthropic/claude-3-haiku).
  - gemini   — Google Gemini (e.g. gemini-2.0-flash). Free tier.
  - groq     — Groq-hosted Llama 3.3 70B. Free tier.
  - claude   — Anthropic Claude (paid API, native).

Default config (this deployment):
  LLM_PROVIDER=aicredits
  LLM_FALLBACK_PROVIDER=groq   (free safety net if the paid balance/gateway errors)

Failover rules:
  - On any exception from the primary, retry once via tenacity.
  - If the primary still fails (or the response can't be parsed in
    `complete_json`), call the fallback provider exactly once.
  - If both fail, raise the most recent exception.

Public API is unchanged:
  llm.load_prompt(name) -> str
  llm.complete(system, user, max_tokens=None) -> str
  llm.complete_json(system, user, max_tokens=None) -> Any
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional

from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings
from app.utils.logger import log

_JSON_BLOCK = re.compile(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", re.S)
_FIRST_JSON = re.compile(r"(\{.*\}|\[.*\])", re.S)


# ────────────────────────────────────────────────────────────────────
# Provider abstraction
# ────────────────────────────────────────────────────────────────────
class BaseProvider(ABC):
    name: str = "base"

    @abstractmethod
    def _do_complete(
        self,
        system: str,
        user: str,
        max_tokens: int,
        json_mode: bool,
    ) -> str:
        """Single non-retrying call. Subclasses implement this."""

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    def complete(
        self,
        system: str,
        user: str,
        max_tokens: int,
        json_mode: bool = False,
    ) -> str:
        return self._do_complete(system, user, max_tokens, json_mode)


class GeminiProvider(BaseProvider):
    name = "gemini"

    def __init__(self) -> None:
        if not settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is empty. Get one free at https://aistudio.google.com/app/apikey")
        from google import genai  # lazy

        self._client = genai.Client(api_key=settings.gemini_api_key)
        self._model = settings.gemini_model

    def _do_complete(
        self,
        system: str,
        user: str,
        max_tokens: int,
        json_mode: bool,
    ) -> str:
        config: dict[str, Any] = {
            "system_instruction": system,
            "max_output_tokens": max_tokens,
            "temperature": 0.4,
        }
        if json_mode:
            config["response_mime_type"] = "application/json"
        resp = self._client.models.generate_content(
            model=self._model,
            contents=user,
            config=config,
        )
        # SDK exposes `.text` as a convenience accessor over candidates
        text = getattr(resp, "text", None)
        if text:
            return text.strip()
        # Fall back to digging into candidates
        try:
            return resp.candidates[0].content.parts[0].text.strip()
        except Exception as e:
            raise RuntimeError(f"Gemini returned no text: {e}; raw={resp!r}")


class GroqProvider(BaseProvider):
    name = "groq"

    def __init__(self) -> None:
        if not settings.groq_api_key:
            raise RuntimeError("GROQ_API_KEY is empty. Get one free at https://console.groq.com/keys")
        from groq import Groq  # lazy

        self._client = Groq(api_key=settings.groq_api_key)
        self._model = settings.groq_model

    def _do_complete(
        self,
        system: str,
        user: str,
        max_tokens: int,
        json_mode: bool,
    ) -> str:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.4,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        resp = self._client.chat.completions.create(**kwargs)
        return (resp.choices[0].message.content or "").strip()


class ClaudeProvider(BaseProvider):
    name = "claude"

    def __init__(self) -> None:
        if not settings.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is empty.")
        from anthropic import Anthropic  # lazy

        self._client = Anthropic(api_key=settings.anthropic_api_key)
        self._model = settings.claude_model

    def _do_complete(
        self,
        system: str,
        user: str,
        max_tokens: int,
        json_mode: bool,
    ) -> str:
        # Claude doesn't have a hard JSON mode; the prompt-level
        # instruction added in LLMClient.complete_json is enough.
        resp = self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        parts = []
        for block in resp.content:
            if getattr(block, "type", None) == "text":
                parts.append(block.text)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "\n".join(parts).strip()


class AiCreditsProvider(BaseProvider):
    """OpenAI-compatible gateway (https://api.aicredits.in/v1). One key serves
    many models (Claude/Gemini/DeepSeek/…) via the standard chat-completions API.

    IMPORTANT: configure a NON-thinking model. Reasoning models spend the
    `max_tokens` budget on hidden thinking and return truncated/empty content
    (finish_reason=length). anthropic/claude-3-haiku is the verified default.
    """

    name = "aicredits"

    def __init__(self) -> None:
        if not settings.aicredits_api_key:
            raise RuntimeError("AICREDITS_API_KEY is empty. Get one at https://aicredits.in")
        import httpx  # lazy

        self._base = settings.aicredits_base_url.rstrip("/")
        self._model = settings.aicredits_model
        self._client = httpx.Client(
            base_url=self._base,
            headers={
                "Authorization": f"Bearer {settings.aicredits_api_key}",
                "Content-Type": "application/json",
            },
            timeout=90.0,
        )

    def _do_complete(
        self,
        system: str,
        user: str,
        max_tokens: int,
        json_mode: bool,
    ) -> str:
        # We don't send response_format: the gateway may return fenced JSON,
        # which LLMClient._parse_json already strips. Keeping the request plain
        # maximises cross-model compatibility through the proxy.
        body: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.4,
        }
        r = self._client.post("/chat/completions", json=body)
        if r.status_code != 200:
            raise RuntimeError(f"AiCredits HTTP {r.status_code}: {r.text[:300]}")
        data = r.json()
        try:
            choice = data["choices"][0]
            content = (choice["message"].get("content") or "").strip()
        except (KeyError, IndexError, TypeError) as e:
            raise RuntimeError(f"AiCredits: unexpected response shape ({e}): {str(data)[:300]}")
        if not content:
            fr = (data.get("choices") or [{}])[0].get("finish_reason")
            raise RuntimeError(
                f"AiCredits returned empty content (finish_reason={fr}). If the configured "
                f"model '{self._model}' is a reasoning/'thinking' model, switch AICREDITS_MODEL "
                "to a non-thinking one like anthropic/claude-3-haiku."
            )
        return content


_PROVIDERS: dict[str, type[BaseProvider]] = {
    "gemini": GeminiProvider,
    "groq": GroqProvider,
    "claude": ClaudeProvider,
    "aicredits": AiCreditsProvider,
}


def _build(name: str) -> BaseProvider:
    cls = _PROVIDERS.get(name.lower())
    if cls is None:
        raise ValueError(
            f"Unknown LLM provider '{name}'. Valid: {sorted(_PROVIDERS)}"
        )
    return cls()


# ────────────────────────────────────────────────────────────────────
# Public facade with primary→fallback failover
# ────────────────────────────────────────────────────────────────────
class LLMClient:
    """Singleton-ish wrapper used by the rest of the app."""

    def __init__(self) -> None:
        self.prompts_dir = Path(settings.prompts_dir)
        self.max_tokens = settings.llm_max_tokens
        self.primary_name = settings.llm_provider.lower()
        self.fallback_name = (settings.llm_fallback_provider or "").lower() or None
        self._primary: Optional[BaseProvider] = None
        self._fallback: Optional[BaseProvider] = None

    # ── prompts ──
    def load_prompt(self, name: str) -> str:
        path = self.prompts_dir / f"{name}.txt"
        if not path.exists():
            raise FileNotFoundError(f"Prompt not found: {path}")
        return path.read_text(encoding="utf-8")

    # ── lazy provider construction ──
    def _get_primary(self) -> BaseProvider:
        if self._primary is None:
            self._primary = _build(self.primary_name)
        return self._primary

    def _get_fallback(self) -> Optional[BaseProvider]:
        if not self.fallback_name or self.fallback_name == self.primary_name:
            return None
        if self._fallback is None:
            try:
                self._fallback = _build(self.fallback_name)
            except Exception as e:
                log.warning(
                    f"Fallback provider '{self.fallback_name}' could not be built: {e}"
                )
                self._fallback = None
        return self._fallback

    # ── core call ──
    def complete(
        self,
        system: str,
        user: str,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> str:
        mt = max_tokens or self.max_tokens
        primary = self._get_primary()
        try:
            return primary.complete(system, user, mt, json_mode=json_mode)
        except Exception as primary_err:
            log.warning(
                f"LLM primary '{primary.name}' failed after retries: {primary_err}"
            )
            fb = self._get_fallback()
            if fb is None:
                raise
            log.info(f"Falling back to '{fb.name}'")
            try:
                return fb.complete(system, user, mt, json_mode=json_mode)
            except Exception as fb_err:
                log.error(f"LLM fallback '{fb.name}' also failed: {fb_err}")
                raise

    def complete_json(
        self,
        system: str,
        user: str,
        max_tokens: int | None = None,
    ) -> Any:
        """Same as complete() but coerces output to parsed JSON.

        Strategy:
          1. Ask provider with json_mode=True (native JSON output where
             supported).
          2. Also nail the instruction at the prompt level — belt + braces.
          3. Strip code fences and find the first JSON value in the response.
        """
        sys_with_json = (
            system
            + "\n\nIMPORTANT: Respond ONLY with a valid JSON value. "
            "No prose, no markdown fences, no commentary."
        )
        raw = self.complete(sys_with_json, user, max_tokens=max_tokens, json_mode=True)
        return self._parse_json(raw)

    # ── parsing helper (exposed for tests) ──
    @staticmethod
    def _parse_json(raw: str) -> Any:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
        m = _JSON_BLOCK.search(raw)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass
        m = _FIRST_JSON.search(raw)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass
        log.error(f"Failed to parse LLM JSON: {raw[:500]}")
        raise ValueError("LLM did not return valid JSON.")


# Single shared instance
llm = LLMClient()
