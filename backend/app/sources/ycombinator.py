"""
Y Combinator Work-at-a-Startup public job search.

WaaS exposes a public Algolia search endpoint. We use the documented
public application id; this is the same API the browser calls.
"""

from __future__ import annotations

from typing import Iterable, List

import httpx

from app.config import settings
from app.sources.base import RawJob
from app.utils.logger import log

ALGOLIA_APP_ID = "45BWZJ1SGC"  # public
ALGOLIA_API_KEY = "Nzk4ODRlMzQyNGE4ZjE0YjQzMjk5MmI5MmYyZmI1MGZkNWE2NjBlZTI4NTRiNDM1MjI4OWY4ZGJiMzU3ZDA1OXZhbGlkVW50aWw9MTcxOTA1Mzg2OQ=="
INDEX = "WaaSPublicJob_production"


class YCombinatorSource:
    name = "ycombinator"

    def __init__(self, query: str | None = None):
        self.query = (query or settings.yc_query or "").strip()

    def fetch(self) -> Iterable[RawJob]:
        if not self.query:
            log.info("YC: empty query, skipping")
            return []
        url = f"https://{ALGOLIA_APP_ID.lower()}-dsn.algolia.net/1/indexes/{INDEX}/query"
        headers = {
            "X-Algolia-Application-Id": ALGOLIA_APP_ID,
            "X-Algolia-API-Key": ALGOLIA_API_KEY,
            "Content-Type": "application/json",
        }
        body = {"query": self.query, "hitsPerPage": 50}
        try:
            with httpx.Client(timeout=20) as client:
                r = client.post(url, headers=headers, json=body)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            log.warning(f"YC fetch failed (endpoint or key may have rotated): {e}")
            return []
        hits = data.get("hits", []) or []
        results: List[RawJob] = []
        for h in hits:
            try:
                slug = h.get("slug") or h.get("objectID")
                url_ = f"https://www.workatastartup.com/jobs/{slug}"
                results.append(
                    RawJob(
                        source=self.name,
                        external_id=str(h.get("objectID") or slug),
                        url=url_,
                        title=h.get("title", "").strip(),
                        company=(h.get("company_name") or h.get("companyName") or "").strip(),
                        location=", ".join(h.get("locations") or []) or None,
                        remote=bool(h.get("remote") or h.get("is_remote")),
                        department=h.get("role") or h.get("role_category"),
                        description=(h.get("description") or "")[:8000],
                        salary_text=h.get("salary_range") or h.get("salary"),
                        raw=h,
                    )
                )
            except Exception as e:
                log.warning(f"YC: skip malformed hit: {e}")
        log.info(f"YC: pulled {len(results)} hits for query '{self.query}'")
        return results
