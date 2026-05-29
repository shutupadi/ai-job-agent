"""
Lever public postings API.

Endpoint:  https://api.lever.co/v0/postings/{company}?mode=json
Public, intended for integrations.
"""

from __future__ import annotations

import time
from typing import Iterable, List

import httpx
from bs4 import BeautifulSoup

from app.config import settings
from app.sources.base import RawJob
from app.utils.logger import log

API = "https://api.lever.co/v0/postings/{company}"


def _strip_html(html: str) -> str:
    if not html:
        return ""
    return BeautifulSoup(html, "lxml").get_text("\n").strip()


class LeverSource:
    name = "lever"

    def __init__(self, companies: List[str] | None = None):
        self.companies = companies or settings.lever_companies

    def fetch(self) -> Iterable[RawJob]:
        if not self.companies:
            log.info("Lever: no companies configured, skipping")
            return []
        results: List[RawJob] = []
        with httpx.Client(timeout=20, follow_redirects=True) as client:
            for company in self.companies:
                company = company.strip()
                if not company:
                    continue
                try:
                    r = client.get(API.format(company=company), params={"mode": "json"})
                    r.raise_for_status()
                except Exception as e:
                    log.warning(f"Lever '{company}' fetch failed: {e}")
                    continue
                data = r.json()
                for job in data:
                    raw = self._convert(company, job)
                    if raw:
                        results.append(raw)
                time.sleep(0.5)
        log.info(f"Lever: pulled {len(results)} postings from {len(self.companies)} companies")
        return results

    def _convert(self, company: str, job: dict) -> RawJob | None:
        try:
            categories = job.get("categories") or {}
            location = categories.get("location")
            department = categories.get("team") or categories.get("department")
            content = _strip_html(job.get("descriptionPlain") or job.get("description", ""))
            extra = "\n\n".join(
                _strip_html(lst.get("content", ""))
                for lst in (job.get("lists") or [])
                if lst.get("content")
            )
            full_desc = (content + "\n\n" + extra).strip()
            remote = "remote" in (location or "").lower() or job.get("workplaceType") == "remote"
            return RawJob(
                source=self.name,
                external_id=job.get("id") or job.get("lever_id") or job.get("text", "")[:64],
                url=job.get("hostedUrl", "") or job.get("applyUrl", ""),
                title=job.get("text", "").strip(),
                company=company.replace("-", " ").title(),
                location=location,
                remote=remote,
                department=department,
                description=full_desc,
                posted_at=str(job.get("createdAt")) if job.get("createdAt") else None,
                raw={"company": company, "data": job},
            )
        except Exception as e:
            log.warning(f"Lever: skip malformed job: {e}")
            return None
