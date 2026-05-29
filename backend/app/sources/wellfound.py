"""
Wellfound (formerly AngelList Talent) — STUB.

No public jobs API. Use a partner feed or authorised crawler.
"""

from __future__ import annotations

from typing import Iterable

from app.config import settings
from app.sources.base import RawJob
from app.utils.logger import log


class WellfoundSource:
    name = "wellfound"

    def fetch(self) -> Iterable[RawJob]:
        if not settings.enable_wellfound:
            return []
        log.warning("Wellfound source is enabled but stubbed.")
        return self._provider_fetch()

    def _provider_fetch(self) -> list[RawJob]:
        return []
