"""
Common types for job sources.

Each source returns an iterable of RawJob.
The pipeline normalises and dedupes before persisting.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Iterable, Optional, Protocol


@dataclass
class RawJob:
    source: str
    external_id: str
    url: str
    title: str
    company: str
    location: Optional[str] = None
    remote: bool = False
    department: Optional[str] = None
    description: str = ""
    salary_text: Optional[str] = None
    posted_at: Optional[str] = None  # ISO string; pipeline parses
    # Whether this posting can be safely auto-applied to. Sources behind
    # anti-bot/login walls (LinkedIn, Naukri) set this False so the pipeline
    # ranks + tailors them but never tries to auto-submit — the user applies
    # manually and marks them applied from the dashboard.
    auto_apply: bool = True
    # How the user applies: "direct" (we could form-fill the company ATS),
    # "external" (apply on the company's site/ATS yourself), or "discovery"
    # (link-out only; e.g. LinkedIn/Naukri scraped listings).
    apply_type: str = "external"
    raw: dict = field(default_factory=dict)

    @property
    def url_hash(self) -> str:
        return hashlib.sha256(self.url.encode("utf-8")).hexdigest()


class JobSource(Protocol):
    name: str

    def fetch(self) -> Iterable[RawJob]: ...
