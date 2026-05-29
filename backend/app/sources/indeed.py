"""
Indeed — STUB.

Indeed's public scraping is also discouraged. Two compliant options:
  a) Indeed Publisher API (deprecated for most accounts; check current
     availability for your region).
  b) A third-party SERP API (Bright Data, SerpAPI, ScraperAPI) that fetches
     Indeed results under their own ToS coverage.

Plug your provider into _provider_fetch().
"""

from __future__ import annotations

from typing import Iterable

from app.config import settings
from app.sources.base import RawJob
from app.utils.logger import log


class IndeedSource:
    name = "indeed"

    def fetch(self) -> Iterable[RawJob]:
        if not settings.enable_indeed:
            return []
        log.warning("Indeed source is enabled but stubbed.")
        return self._provider_fetch()

    def _provider_fetch(self) -> list[RawJob]:
        return []
