"""
Adzuna Jobs API — keyword-searched listings aggregated from thousands of
companies + boards (incl. Goldman Sachs, Bloomberg, big tech, banks, startups).

This is the high-volume, relevant, ToS-clean source. Free tier: register an app
at https://developer.adzuna.com → set ADZUNA_APP_ID + ADZUNA_APP_KEY.

Because Adzuna already searches by keyword, results are far more on-target than a
generic board crawl. Descriptions are snippets (not full JDs) — enough for
relevance pre-filtering + ranking.

Docs: https://developer.adzuna.com/docs/search
"""

from __future__ import annotations

import time
from itertools import product
from typing import Iterable, List

import httpx

from app.config import settings
from app.sources.base import RawJob
from app.utils.logger import log

_BASE = "https://api.adzuna.com/v1/api/jobs"
_REMOTE_HINT = ("remote", "work from home", "wfh", "anywhere")


class AdzunaSource:
    name = "adzuna"

    def fetch(self) -> Iterable[RawJob]:
        if not settings.enable_adzuna:
            return []
        if not (settings.adzuna_app_id and settings.adzuna_app_key):
            log.warning("Adzuna enabled but ADZUNA_APP_ID/ADZUNA_APP_KEY not set; skipping.")
            return []

        country = (settings.adzuna_country or "in").lower()
        keywords = (settings.keywords or ["software engineer"])[:5]
        locations = [l for l in (settings.locations or []) if l] or [""]
        # Keep India + the user's cities; skip pure "Remote"/country tokens as a
        # `where` (Adzuna treats those poorly) — search them without a location.
        locs = []
        for l in locations[:3]:
            ll = l.lower()
            locs.append("" if ll in ("remote", "india", "anywhere") else l)
        locs = list(dict.fromkeys(locs)) or [""]

        cap = max(10, settings.adzuna_max)
        per_page = 50
        results: List[RawJob] = []
        seen: set[str] = set()

        try:
            with httpx.Client(timeout=20, follow_redirects=True) as client:
                for kw, where in product(keywords, locs):
                    if len(results) >= cap:
                        break
                    page = 1
                    while len(results) < cap and page <= 2:
                        params = {
                            "app_id": settings.adzuna_app_id,
                            "app_key": settings.adzuna_app_key,
                            "results_per_page": per_page,
                            "what": kw,
                            "max_days_old": 30,
                            "sort_by": "date",
                            "content-type": "application/json",
                        }
                        if where:
                            params["where"] = where
                        try:
                            r = client.get(f"{_BASE}/{country}/search/{page}", params=params)
                        except Exception as e:
                            log.debug(f"Adzuna req error '{kw}'/'{where}': {e}")
                            break
                        if r.status_code != 200:
                            log.debug(f"Adzuna '{kw}'/'{where}' p{page} -> HTTP {r.status_code}")
                            break
                        items = (r.json() or {}).get("results", []) or []
                        if not items:
                            break
                        for it in items:
                            raw = self._convert(it)
                            if raw and raw.external_id not in seen:
                                seen.add(raw.external_id)
                                results.append(raw)
                                if len(results) >= cap:
                                    break
                        page += 1
                        time.sleep(0.4)  # polite pacing
        except Exception as e:
            log.warning(f"Adzuna fetch aborted: {e}")

        log.info(f"Adzuna: pulled {len(results)} listings")
        return results

    def _convert(self, it: dict) -> RawJob | None:
        try:
            ext = str(it.get("id") or "")
            url = it.get("redirect_url") or ""
            title = (it.get("title") or "").strip()
            if not ext or not title or not url:
                return None
            company = ((it.get("company") or {}).get("display_name") or "Unknown").strip()
            location = (it.get("location") or {}).get("display_name")
            desc = (it.get("description") or "").strip()
            blob = f"{title} {location or ''} {desc}".lower()
            remote = any(h in blob for h in _REMOTE_HINT)
            salary_text = None
            smin, smax = it.get("salary_min"), it.get("salary_max")
            if smin or smax:
                salary_text = f"{int(smin or 0):,}–{int(smax or 0):,}"
            return RawJob(
                source=self.name,
                external_id=ext,
                url=url.split("?")[0] if "?" in url else url,
                title=title,
                company=company,
                location=location,
                remote=remote,
                description=desc,
                salary_text=salary_text,
                posted_at=it.get("created"),  # ISO string; pipeline parses
                auto_apply=False,  # redirects to the company/board — user applies
                raw={"adzuna_id": ext},
            )
        except Exception as e:
            log.debug(f"Adzuna: skip item: {e}")
            return None
