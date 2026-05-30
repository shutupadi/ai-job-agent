"""Source registry — central place to enumerate enabled sources."""

from __future__ import annotations

from typing import List

from app.config import settings
from app.sources.adzuna import AdzunaSource
from app.sources.base import JobSource
from app.sources.greenhouse import GreenhouseSource
from app.sources.indeed import IndeedSource
from app.sources.lever import LeverSource
from app.sources.linkedin import LinkedInSource
from app.sources.naukri import NaukriSource
from app.sources.oracle import OracleSource
from app.sources.wellfound import WellfoundSource
from app.sources.workday import WorkdaySource
from app.sources.ycombinator import YCombinatorSource


def enabled_sources() -> List[JobSource]:
    sources: List[JobSource] = []
    if settings.enable_greenhouse:
        sources.append(GreenhouseSource())
    if settings.enable_lever:
        sources.append(LeverSource())
    if settings.enable_ycombinator:
        sources.append(YCombinatorSource())
    if settings.enable_workday:
        sources.append(WorkdaySource())
    if settings.enable_oracle:
        sources.append(OracleSource())
    if settings.enable_linkedin:
        sources.append(LinkedInSource())
    if settings.enable_indeed:
        sources.append(IndeedSource())
    if settings.enable_naukri:
        sources.append(NaukriSource())
    if settings.enable_wellfound:
        sources.append(WellfoundSource())
    if settings.enable_adzuna:
        sources.append(AdzunaSource())
    return sources
