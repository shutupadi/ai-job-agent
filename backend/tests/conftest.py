"""Pytest config — make `app.*` importable without installing the package."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("GEMINI_API_KEY", "test-key")
os.environ.setdefault("GROQ_API_KEY", "test-key")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("LLM_PROVIDER", "gemini")
os.environ.setdefault("LLM_FALLBACK_PROVIDER", "groq")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
# Tests hammer endpoints far faster than real users — disable the IP limiter so
# integration tests aren't throttled. (test_rate_limit.py toggles it back on.)
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")
