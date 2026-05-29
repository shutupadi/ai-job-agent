"""
Workday-hosted career sites.

A large share of "top product company career portals" run on Workday. Each
tenant exposes a *public* JSON search endpoint that the company's own careers
page calls from the browser — no auth, no scraping of rendered HTML:

    POST https://{host}/wday/cxs/{tenant}/{site}/jobs
         {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": ""}

and a per-posting detail endpoint:

    GET  https://{host}/wday/cxs/{tenant}/{site}{externalPath}

Configure tenants in .env via WORKDAY_TENANTS as comma-separated
"host|tenant|site" (optionally a 4th "|Display Name") entries, e.g.

    nvidia.wd5.myworkdayjobs.com|nvidia|NVIDIAExternalCareerSite|NVIDIA

These career sites are public, but layouts/req-ids differ per tenant, so this
adapter is defensive: any tenant/posting that fails is logged and skipped.
We auto-apply attempts are still made downstream (Workday applications require
account creation + multi-step forms, so they frequently fall back to manual).
"""

from __future__ import annotations

import time
from typing import Iterable, List, Optional, Tuple

import httpx
from bs4 import BeautifulSoup

from app.config import settings
from app.sources.base import RawJob
from app.utils.logger import log

_HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    ),
}


def _strip_html(html: str) -> str:
    if not html:
        return ""
    return BeautifulSoup(html, "lxml").get_text("\n").strip()


def _parse_entry(entry: str) -> Optional[Tuple[str, str, str, Optional[str]]]:
    """'host|tenant|site[|Display]' -> (host, tenant, site, display)."""
    parts = [p.strip() for p in entry.split("|")]
    if len(parts) < 3 or not all(parts[:3]):
        log.warning(f"Workday: ignoring malformed WORKDAY_TENANTS entry: {entry!r}")
        return None
    host, tenant, site = parts[0], parts[1], parts[2]
    display = parts[3] if len(parts) >= 4 and parts[3] else None
    return host, tenant, site, display


class WorkdaySource:
    name = "workday"

    def __init__(self, tenants: List[str] | None = None):
        self.tenants = tenants or settings.workday_tenants

    def fetch(self) -> Iterable[RawJob]:
        if not self.tenants:
            log.info("Workday: no tenants configured, skipping")
            return []
        results: List[RawJob] = []
        with httpx.Client(timeout=25, follow_redirects=True, headers=_HEADERS) as client:
            for entry in self.tenants:
                parsed = _parse_entry(entry)
                if not parsed:
                    continue
                host, tenant, site, display = parsed
                try:
                    results.extend(self._fetch_tenant(client, host, tenant, site, display))
                except Exception as e:
                    log.warning(f"Workday '{host}/{tenant}/{site}' failed: {e}")
                time.sleep(0.6)
        log.info(f"Workday: pulled {len(results)} postings from {len(self.tenants)} tenant(s)")
        return results

    def _fetch_tenant(
        self,
        client: httpx.Client,
        host: str,
        tenant: str,
        site: str,
        display: Optional[str],
    ) -> List[RawJob]:
        base = f"https://{host}/wday/cxs/{tenant}/{site}"
        out: List[RawJob] = []
        company = display or tenant.replace("-", " ").replace("_", " ").title()
        limit = 20
        offset = 0
        cap = max(1, settings.workday_max_per_tenant)
        searches = settings.keywords or [""]
        # Use the first couple of keywords to keep request volume modest.
        for search_text in searches[:2]:
            offset = 0
            while len(out) < cap:
                body = {
                    "appliedFacets": {},
                    "limit": limit,
                    "offset": offset,
                    "searchText": (search_text or "").strip(),
                }
                r = client.post(f"{base}/jobs", json=body)
                r.raise_for_status()
                data = r.json()
                postings = data.get("jobPostings") or []
                if not postings:
                    break
                for p in postings:
                    raw = self._convert(client, base, host, site, company, p)
                    if raw:
                        out.append(raw)
                    if len(out) >= cap:
                        break
                total = int(data.get("total") or 0)
                offset += limit
                if offset >= total:
                    break
                time.sleep(0.4)
        # De-dupe within tenant by external_id (same job can match 2 keywords).
        seen: set[str] = set()
        deduped: List[RawJob] = []
        for j in out:
            if j.external_id in seen:
                continue
            seen.add(j.external_id)
            deduped.append(j)
        return deduped

    def _convert(
        self,
        client: httpx.Client,
        base: str,
        host: str,
        site: str,
        company: str,
        p: dict,
    ) -> RawJob | None:
        try:
            external_path = p.get("externalPath") or ""
            title = (p.get("title") or "").strip()
            location = p.get("locationsText") or None
            req_id = p.get("bulletFields") or []
            external_id = (req_id[0] if req_id else None) or external_path or title
            human_url = f"https://{host}/{site}{external_path}" if external_path else f"https://{host}/{site}"

            description = ""
            # Best-effort detail fetch for the JD (powers ranking + tailoring).
            if external_path:
                try:
                    d = client.get(f"{base}{external_path}")
                    if d.status_code == 200:
                        info = (d.json() or {}).get("jobPostingInfo") or {}
                        description = _strip_html(info.get("jobDescription") or "")
                        location = info.get("location") or location
                        human_url = info.get("externalUrl") or human_url
                    time.sleep(0.3)
                except Exception as e:
                    log.debug(f"Workday detail fetch failed for {external_path}: {e}")

            loc_l = (location or "").lower()
            remote = "remote" in loc_l or "remote" in description.lower()[:500]
            return RawJob(
                source=self.name,
                external_id=str(external_id),
                url=human_url,
                title=title,
                company=company,
                location=location,
                remote=remote,
                description=description,
                auto_apply=True,  # we attempt Workday auto-apply (best-effort)
                raw={"host": host, "site": site, "data": p},
            )
        except Exception as e:
            log.warning(f"Workday: skip malformed posting: {e}")
            return None
