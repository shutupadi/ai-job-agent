"""
Naukri.com — PUBLIC search JSON, RANK-ONLY.

Same boundaries as the LinkedIn adapter:
  * Public, unauthenticated search endpoint only (the one naukri.com's own
    frontend calls). No login, no captcha/Incapsula evasion, no proxies.
  * Capped (NAUKRI_MAX) and rate-limited.
  * auto_apply=False — ranked + tailored, but the user applies on Naukri
    manually and marks it applied from the dashboard.

Naukri sits behind aggressive bot protection, so server-side calls often get
403/blocked. This adapter is genuinely best-effort: if it's blocked it logs a
clear message and returns nothing rather than fighting the protection.
"""

from __future__ import annotations

from typing import Iterable, List, Optional

import httpx

from app.config import settings
from app.sources.base import RawJob
from app.utils.logger import log

SEARCH = "https://www.naukri.com/jobapi/v3/search"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "appid": "109",
    "systemid": "109",
    "Referer": "https://www.naukri.com/",
}


def _placeholder(job: dict, kind: str) -> Optional[str]:
    for ph in job.get("placeholders") or []:
        if ph.get("type") == kind:
            return ph.get("label")
    return None


class NaukriSource:
    name = "naukri"

    def fetch(self) -> Iterable[RawJob]:
        if not settings.enable_naukri:
            return []
        cap = max(1, settings.naukri_max)
        keywords = settings.keywords or ["Software Engineer"]
        results: List[RawJob] = []
        seen: set[str] = set()

        try:
            with httpx.Client(timeout=20, follow_redirects=True, headers=_HEADERS) as client:
                for kw in keywords:
                    if len(results) >= cap:
                        break
                    for raw in self._search(client, kw):
                        if len(results) >= cap:
                            break
                        if raw.external_id in seen:
                            continue
                        seen.add(raw.external_id)
                        results.append(raw)
        except Exception as e:
            log.warning(f"Naukri fetch aborted (likely bot-protection block): {e}")

        if not results:
            log.info("Naukri: 0 listings (endpoint may be blocking server-side calls)")
        else:
            log.info(f"Naukri: pulled {len(results)} public listings (rank-only)")
        return results

    def _search(self, client: httpx.Client, keyword: str) -> List[RawJob]:
        kw = keyword.strip()
        seo = kw.lower().replace(" ", "-")
        params = {
            "noOfResults": 20,
            "urlType": "search_by_keyword",
            "searchType": "adv",
            "keyword": kw,
            "k": kw,
            "seoKey": f"{seo}-jobs",
            "src": "jobsearchDesk",
            "pageNo": 1,
        }
        try:
            r = client.get(SEARCH, params=params)
            if r.status_code != 200:
                log.debug(f"Naukri '{kw}' -> HTTP {r.status_code}")
                return []
            data = r.json()
        except Exception as e:
            log.debug(f"Naukri '{kw}' error: {e}")
            return []

        out: List[RawJob] = []
        for job in data.get("jobDetails") or []:
            raw = self._convert(job)
            if raw:
                out.append(raw)
        return out

    def _convert(self, job: dict) -> RawJob | None:
        try:
            job_id = job.get("jobId") or job.get("jdURL") or ""
            jd_url = job.get("jdURL") or ""
            if jd_url and not jd_url.startswith("http"):
                jd_url = "https://www.naukri.com" + jd_url
            location = _placeholder(job, "location")
            salary = _placeholder(job, "salary")
            desc = job.get("jobDescription") or job.get("tagsAndSkills") or ""
            remote = bool(location and "remote" in location.lower())
            return RawJob(
                source=self.name,
                external_id=str(job_id),
                url=jd_url or "https://www.naukri.com/",
                title=(job.get("title") or "").strip(),
                company=(job.get("companyName") or "Unknown").strip(),
                location=location,
                remote=remote,
                description=str(desc),
                salary_text=salary,
                auto_apply=False,  # rank-only: user applies on Naukri manually
                raw={"naukri_job_id": job_id},
            )
        except Exception as e:
            log.debug(f"Naukri: skip malformed job: {e}")
            return None
