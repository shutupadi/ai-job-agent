"""
SmartRecruiters public Posting API.

Endpoints (public, no auth — meant for job-board syndication):
  list:   https://api.smartrecruiters.com/v1/companies/{company}/postings?limit=100
  detail: https://api.smartrecruiters.com/v1/companies/{company}/postings/{id}

Configure companies via SMARTRECRUITERS_COMPANIES (comma-separated identifiers,
e.g. "Visa,Square,Bosch"). Fails gracefully when unset. We cap detail fetches per
company to stay polite and fast.
"""

from __future__ import annotations

import time
from typing import Iterable, List

import httpx
from bs4 import BeautifulSoup

from app.config import settings
from app.sources.base import RawJob
from app.utils.logger import log

LIST_API = "https://api.smartrecruiters.com/v1/companies/{company}/postings"
DETAIL_API = "https://api.smartrecruiters.com/v1/companies/{company}/postings/{pid}"


def _strip_html(html: str) -> str:
    if not html:
        return ""
    return BeautifulSoup(html, "lxml").get_text("\n").strip()


class SmartRecruitersSource:
    name = "smartrecruiters"

    def __init__(self, companies: List[str] | None = None):
        self.companies = companies if companies is not None else settings.smartrecruiters_companies
        self.max_per_company = settings.smartrecruiters_max_per_company

    def fetch(self) -> Iterable[RawJob]:
        if not self.companies:
            log.info("SmartRecruiters: no companies configured, skipping")
            return []
        results: List[RawJob] = []
        with httpx.Client(timeout=20, follow_redirects=True) as client:
            for company in self.companies:
                company = company.strip()
                if not company:
                    continue
                try:
                    r = client.get(LIST_API.format(company=company), params={"limit": 100})
                    r.raise_for_status()
                    postings = r.json().get("content", [])[: self.max_per_company]
                except Exception as e:
                    log.warning(f"SmartRecruiters '{company}' list failed: {e}")
                    continue
                for p in postings:
                    raw = self._convert(client, company, p)
                    if raw:
                        results.append(raw)
                    time.sleep(0.3)
        log.info(
            f"SmartRecruiters: pulled {len(results)} postings from {len(self.companies)} companies"
        )
        return results

    def _convert(self, client: httpx.Client, company: str, p: dict) -> RawJob | None:
        try:
            pid = str(p.get("id"))
            loc = p.get("location") or {}
            city = ", ".join(x for x in (loc.get("city"), loc.get("region"), loc.get("country")) if x)
            remote = bool(loc.get("remote"))
            comp_name = (p.get("company") or {}).get("name") or company
            # Apply URL: SmartRecruiters jobs.smartrecruiters.com posting page.
            url = (
                f"https://jobs.smartrecruiters.com/{company}/{pid}"
                if pid
                else (p.get("ref") or "")
            )
            description = ""
            try:
                d = client.get(DETAIL_API.format(company=company, pid=pid))
                if d.status_code == 200:
                    sections = ((d.json().get("jobAd") or {}).get("sections")) or {}
                    parts = [
                        (sections.get(k) or {}).get("text", "")
                        for k in ("jobDescription", "qualifications", "additionalInformation")
                    ]
                    description = _strip_html("\n".join(p for p in parts if p))
            except Exception:
                pass
            return RawJob(
                source=self.name,
                external_id=pid,
                url=url,
                title=(p.get("name") or "").strip(),
                company=comp_name,
                location=city or None,
                remote=remote,
                department=(p.get("department") or {}).get("label"),
                description=description,
                posted_at=p.get("releasedDate"),
                apply_type="external",
                raw={"company": company, "data": p},
            )
        except Exception as e:
            log.warning(f"SmartRecruiters: skip malformed job: {e}")
            return None
