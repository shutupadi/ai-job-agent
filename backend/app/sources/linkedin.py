"""
LinkedIn Jobs — PUBLIC guest listings, RANK-ONLY.

Important boundaries (read before changing):
  * We only hit LinkedIn's *public, unauthenticated* "guest" job-search
    endpoint — the same one the logged-out jobs page calls. No login, no
    cookies, no captcha solving, no proxy rotation. That kind of evasion is
    against LinkedIn's ToS and gets your IP banned — and the user explicitly
    asked us NOT to bypass safety features.
  * Volume is capped (LINKEDIN_MAX) and every request is rate-limited. Keep it
    low: this is for a single person's job hunt, not bulk harvesting.
  * Jobs from here are marked auto_apply=False — the pipeline ranks + tailors
    them, but NEVER auto-submits. The user applies on LinkedIn manually and
    marks them applied from the dashboard.

This is best-effort: LinkedIn changes markup and may rate-limit/return 429/999.
On any failure we log and return what we have.
"""

from __future__ import annotations

import re
import time
from itertools import product
from typing import Iterable, List, Optional

import httpx
from bs4 import BeautifulSoup

from app.config import settings
from app.sources.base import RawJob
from app.utils.logger import log

GUEST_SEARCH = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.linkedin.com/jobs",
}

_ID_RE = re.compile(r"(\d{6,})")


class LinkedInSource:
    name = "linkedin"

    def fetch(self) -> Iterable[RawJob]:
        if not settings.enable_linkedin:
            return []
        cap = max(1, settings.linkedin_max)
        keywords = settings.keywords or ["Software Engineer"]
        # Bias locations toward India + Remote; fall back to "India".
        locations = [l for l in settings.locations if l] or ["India"]
        results: List[RawJob] = []
        seen: set[str] = set()

        try:
            with httpx.Client(timeout=20, follow_redirects=True, headers=_HEADERS) as client:
                for kw, loc in product(keywords, locations):
                    if len(results) >= cap:
                        break
                    cards = self._search(client, kw, loc)
                    for card in cards:
                        if len(results) >= cap:
                            break
                        raw = self._card_to_raw(client, card)
                        if not raw or raw.external_id in seen:
                            continue
                        seen.add(raw.external_id)
                        results.append(raw)
                    time.sleep(1.3)  # polite pacing between searches
        except Exception as e:
            log.warning(f"LinkedIn fetch aborted (public endpoint may be rate-limiting): {e}")

        log.info(f"LinkedIn: pulled {len(results)} public listings (rank-only)")
        return results

    def _search(self, client: httpx.Client, keywords: str, location: str):
        params = {"keywords": keywords, "location": location, "start": 0}
        # LinkedIn's remote work-type filter.
        if "remote" in location.lower():
            params["f_WT"] = 2
        try:
            r = client.get(GUEST_SEARCH, params=params)
            if r.status_code != 200 or not r.text.strip():
                log.debug(f"LinkedIn search '{keywords}'/'{location}' -> HTTP {r.status_code}")
                return []
            soup = BeautifulSoup(r.text, "lxml")
            return soup.select("li") or soup.select("div.base-card")
        except Exception as e:
            log.debug(f"LinkedIn search error '{keywords}'/'{location}': {e}")
            return []

    def _card_to_raw(self, client: httpx.Client, card) -> Optional[RawJob]:
        try:
            link_el = card.select_one("a.base-card__full-link") or card.select_one("a[href*='/jobs/view/']")
            title_el = card.select_one("h3.base-search-card__title")
            company_el = card.select_one("h4.base-search-card__subtitle")
            loc_el = card.select_one("span.job-search-card__location")
            if not (link_el and title_el):
                return None
            url = (link_el.get("href") or "").split("?")[0].strip()
            if not url:
                return None

            external_id = None
            urn_el = card.select_one("[data-entity-urn]") or card.select_one("div.base-card[data-entity-urn]")
            if urn_el and urn_el.get("data-entity-urn"):
                m = _ID_RE.search(urn_el["data-entity-urn"])
                if m:
                    external_id = m.group(1)
            if not external_id:
                m = _ID_RE.search(url)
                external_id = m.group(1) if m else url

            title = title_el.get_text(strip=True)
            company = company_el.get_text(strip=True) if company_el else "Unknown"
            location = loc_el.get_text(strip=True) if loc_el else None
            remote = bool(location and "remote" in location.lower())

            description = self._fetch_description(client, external_id)
            return RawJob(
                source=self.name,
                external_id=str(external_id),
                url=url,
                title=title,
                company=company,
                location=location,
                remote=remote,
                description=description,
                auto_apply=False,  # rank-only: user applies on LinkedIn manually
                raw={"linkedin_job_id": external_id},
            )
        except Exception as e:
            log.debug(f"LinkedIn: skip card: {e}")
            return None

    def _fetch_description(self, client: httpx.Client, job_id: str) -> str:
        """Best-effort public JD fetch for better ranking. Failure is fine."""
        if not job_id or not job_id.isdigit():
            return ""
        url = f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"
        try:
            time.sleep(0.8)
            r = client.get(url)
            if r.status_code != 200:
                return ""
            soup = BeautifulSoup(r.text, "lxml")
            node = soup.select_one("div.show-more-less-html__markup") or soup.select_one(
                "section.show-more-less-html"
            )
            return node.get_text("\n").strip()[:6000] if node else ""
        except Exception:
            return ""
