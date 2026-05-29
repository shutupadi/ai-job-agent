"""
Regression test for the pydantic-settings list-from-CSV bug.

Symptom that prompted this test:
  pydantic_settings.sources.SettingsError: error parsing value for
  field "keywords" from source "EnvSettingsSource"

The bug: pydantic v2 BaseSettings tries to json.loads() any env var typed
as a list before validators run. So `KEYWORDS=SDE,Software Engineer`
crashed the loader. Fix: store as `str`, expose `List[str]` via @property.
"""

from __future__ import annotations

import os

os.environ["KEYWORDS"] = "SDE,Software Engineer,Backend,Machine Learning"
os.environ["LOCATIONS"] = "Noida,Gurgaon,Bangalore,Hyderabad,Pune,Remote"
os.environ["GREENHOUSE_BOARDS"] = "stripe,airbnb,doordash,robinhood"
os.environ["LEVER_COMPANIES"] = "palantir,netflix,brex"
os.environ.setdefault("GEMINI_API_KEY", "test")
os.environ.setdefault("GROQ_API_KEY", "test")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")


def test_csv_env_vars_load_as_lists():
    # Clear the lru_cache so we re-read with the env we just set
    from app.config import Settings

    s = Settings()
    assert s.keywords == [
        "SDE",
        "Software Engineer",
        "Backend",
        "Machine Learning",
    ]
    assert s.locations == [
        "Noida",
        "Gurgaon",
        "Bangalore",
        "Hyderabad",
        "Pune",
        "Remote",
    ]
    assert s.greenhouse_boards == ["stripe", "airbnb", "doordash", "robinhood"]
    assert s.lever_companies == ["palantir", "netflix", "brex"]


def test_empty_csv_env_var_returns_empty_list():
    from app.config import Settings

    s = Settings(GREENHOUSE_BOARDS="", LEVER_COMPANIES="")
    assert s.greenhouse_boards == []
    assert s.lever_companies == []


def test_csv_with_extra_whitespace_is_trimmed():
    from app.config import Settings

    s = Settings(KEYWORDS=" SDE ,  Software Engineer ,Backend  ")
    assert s.keywords == ["SDE", "Software Engineer", "Backend"]
