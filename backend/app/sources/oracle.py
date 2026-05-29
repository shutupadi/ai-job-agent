"""
Oracle Recruiting Cloud (Candidate Experience) career sites.

A huge share of banks and large enterprises run their careers portal on Oracle
Fusion "CE" (e.g. JPMorgan Chase). Each site exposes the *same* public JSON
endpoint that the company's own careers page calls from the browser — no auth,
no HTML scraping:

    GET https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions
        ?onlyData=true
        &expand=requisitionList.secondaryLocations,requisitionList.requisitionFlexFields
        &finder=findReqs;siteNumber={site},facetsList=...,limit={n},offset={m},
                sortBy=POSTING_DATES_DESC[,keyword={kw}]

and a per-posting detail endpoint:

    GET https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails
        ?expand=all&onlyData=true&finder=ById;Id="{id}",siteNumber={site}

Configure sites in .env via ORACLE_TENANTS as comma-separated
"host|siteNumber" (optionally a 3rd "|Display Name") entries, e.g.

    jpmc.fa.oraclecloud.com|CX_1001|JPMorgan Chase

Find the host + siteNumber by opening a company's Oracle careers page; the URL
looks like https://{host}/hcmUI/CandidateExperience/en/sites/CX_1001/...

Applying on Oracle CE almost always requires creating an account + a multi-step
form, so (like Workday) auto-apply is attempted best-effort and usually falls
back to the manual "awaiting approval" bucket — we never create accounts.
"""

from __future__ import annotations

import time
from typing import Iterable, List, Optional, Tuple
from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup

from app.config import settings
from app.sources.base import RawJob
from app.utils.logger import log

_HEADERS = {
    "Accept": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    ),
}

# Facets the CE UI normally requests; harmless to include, keeps the response
# shape identical to what the real careers page receives.
_FACETS = (
    "LOCATIONS;WORK_LOCATIONS;WORKPLACE_TYPES;TITLES;CATEGORIES;"
    "ORGANIZATIONS;POSTING_DATES;FLEX_FIELDS"
)


def _strip_html(html: str) -> str:
    if not html:
        return ""
    return BeautifulSoup(html, "lxml").get_text("\n").strip()


def _parse_entry(entry: str) -> Optional[Tuple[str, str, Optional[str]]]:
    """'host|siteNumber[|Display]' -> (host, site, display)."""
    parts = [p.strip() for p in entry.split("|")]
    if len(parts) < 2 or not all(parts[:2]):
        log.warning(f"Oracle: ignoring malformed ORACLE_TENANTS entry: {entry!r}")
        return None
    host, site = parts[0], parts[1]
    display = parts[2] if len(parts) >= 3 and parts[2] else None
    return host, site, display


class OracleSource:
    name = "oracle"

    def __init__(self, tenants: List[str] | None = None):
        self.tenants = tenants or settings.oracle_tenants

    def fetch(self) -> Iterable[RawJob]:
        if not self.tenants:
            log.info("Oracle: no tenants configured, skipping")
            return []
        results: List[RawJob] = []
        with httpx.Client(timeout=25, follow_redirects=True, headers=_HEADERS) as client:
            for entry in self.tenants:
                parsed = _parse_entry(entry)
                if not parsed:
                    continue
                host, site, display = parsed
                try:
                    results.extend(self._fetch_site(client, host, site, display))
                except Exception as e:
                    log.warning(f"Oracle '{host}/{site}' failed: {e}")
                time.sleep(0.6)
        log.info(f"Oracle: pulled {len(results)} postings from {len(self.tenants)} site(s)")
        return results

    def _list_url(self, host: str, site: str, limit: int, offset: int, kw: str) -> str:
        finder = (
            f"findReqs;siteNumber={site},facetsList={_FACETS},"
            f"limit={limit},offset={offset},sortBy=POSTING_DATES_DESC"
        )
        if kw:
            finder += f",keyword={quote(kw)}"
        return (
            f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
            f"?onlyData=true"
            f"&expand=requisitionList.secondaryLocations,requisitionList.requisitionFlexFields"
            f"&finder={finder}"
        )

    def _fetch_site(
        self,
        client: httpx.Client,
        host: str,
        site: str,
        display: Optional[str],
    ) -> List[RawJob]:
        out: List[RawJob] = []
        company = display or host.split(".")[0].upper()
        limit = 25
        cap = max(1, settings.oracle_max_per_tenant)
        searches = settings.keywords or [""]
        # Use the first couple of keywords to keep request volume modest.
        for kw in searches[:2]:
            offset = 0
            while len(out) < cap:
                url = self._list_url(host, site, limit, offset, (kw or "").strip())
                r = client.get(url)
                r.raise_for_status()
                data = r.json()
                items = data.get("items") or []
                if not items:
                    break
                req_list = items[0].get("requisitionList") or []
                if not req_list:
                    break
                for job in req_list:
                    raw = self._convert(client, host, site, company, job)
                    if raw:
                        out.append(raw)
                    if len(out) >= cap:
                        break
                total = int(items[0].get("TotalJobsCount") or 0)
                offset += limit
                if offset >= total or not data.get("hasMore", False):
                    break
                time.sleep(0.4)
        # De-dupe within site by external_id (same job can match 2 keywords).
        seen: set[str] = set()
        deduped: List[RawJob] = []
        for j in out:
            if j.external_id in seen:
                continue
            seen.add(j.external_id)
            deduped.append(j)
        return deduped

    def _fetch_description(
        self, client: httpx.Client, host: str, site: str, job_id: str
    ) -> str:
        """Best-effort full JD fetch (powers ranking + tailoring)."""
        try:
            url = (
                f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails"
                f"?expand=all&onlyData=true"
                f'&finder=ById;Id="{job_id}",siteNumber={site}'
            )
            d = client.get(url)
            if d.status_code != 200:
                return ""
            items = (d.json() or {}).get("items") or []
            if not items:
                return ""
            info = items[0]
            parts = [
                info.get("ExternalDescriptionStr") or "",
                info.get("ResponsibilitiesStr") or "",
                info.get("CorporateDescriptionStr") or "",
            ]
            time.sleep(0.3)
            return _strip_html("\n".join(p for p in parts if p))
        except Exception as e:
            log.debug(f"Oracle detail fetch failed for {job_id}: {e}")
            return ""

    def _convert(
        self,
        client: httpx.Client,
        host: str,
        site: str,
        company: str,
        job: dict,
    ) -> RawJob | None:
        try:
            job_id = str(job.get("Id") or "").strip()
            title = (job.get("Title") or "").strip()
            if not job_id or not title:
                return None

            # Location: primary + any secondary locations, comma-joined.
            location = job.get("PrimaryLocation") or None
            secondary = job.get("secondaryLocations") or []
            sec_names = [
                s.get("Name") for s in secondary if isinstance(s, dict) and s.get("Name")
            ]
            if sec_names:
                location = ", ".join(filter(None, [location, *sec_names]))

            workplace = (job.get("WorkplaceTypeCode") or "").upper()
            short = _strip_html(job.get("ShortDescriptionStr") or "")
            description = self._fetch_description(client, host, site, job_id) or short

            remote = (
                "REMOTE" in workplace
                or "remote" in (location or "").lower()
                or "remote" in description.lower()[:500]
            )

            human_url = (
                f"https://{host}/hcmUI/CandidateExperience/en/sites/{site}/job/{job_id}"
            )
            return RawJob(
                source=self.name,
                external_id=job_id,
                url=human_url,
                title=title,
                company=company,
                location=location,
                remote=remote,
                description=description,
                posted_at=job.get("PostedDate") or None,
                auto_apply=True,  # attempt best-effort; usually -> manual (account wall)
                raw={"host": host, "site": site, "data": job},
            )
        except Exception as e:
            log.warning(f"Oracle: skip malformed posting: {e}")
            return None
