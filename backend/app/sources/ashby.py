"""
Ashby public job-board API.

Endpoint: https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true

This is Ashby's official PUBLIC posting API, intended for embedding company job
boards on third-party sites — no scraping, ToS-friendly. Configure boards via
ASHBY_BOARDS (comma-separated job-board names, e.g. "openai,ramp,notion").
Fails gracefully when unset.
"""

from __future__ import annotations

import time
from typing import Iterable, List

import httpx

from app.config import settings
from app.sources.base import RawJob
from app.utils.logger import log

API = "https://api.ashbyhq.com/posting-api/job-board/{board}"


class AshbySource:
    name = "ashby"

    def __init__(self, boards: List[str] | None = None):
        self.boards = boards if boards is not None else settings.ashby_boards

    def fetch(self) -> Iterable[RawJob]:
        if not self.boards:
            log.info("Ashby: no boards configured, skipping")
            return []
        results: List[RawJob] = []
        with httpx.Client(timeout=20, follow_redirects=True) as client:
            for board in self.boards:
                board = board.strip()
                if not board:
                    continue
                try:
                    r = client.get(
                        API.format(board=board),
                        params={"includeCompensation": "true"},
                    )
                    r.raise_for_status()
                    data = r.json()
                except Exception as e:
                    log.warning(f"Ashby '{board}' fetch failed: {e}")
                    continue
                org = data.get("name") or board
                for job in data.get("jobs", []):
                    raw = self._convert(board, org, job)
                    if raw:
                        results.append(raw)
                time.sleep(0.5)
        log.info(f"Ashby: pulled {len(results)} postings from {len(self.boards)} boards")
        return results

    def _convert(self, board: str, org: str, job: dict) -> RawJob | None:
        try:
            comp = job.get("compensation") or {}
            salary = None
            summary = comp.get("compensationTierSummary") if isinstance(comp, dict) else None
            if summary:
                salary = str(summary)
            return RawJob(
                source=self.name,
                external_id=str(job.get("id")),
                url=job.get("jobUrl") or job.get("applyUrl") or "",
                title=(job.get("title") or "").strip(),
                company=org,
                location=job.get("location") or (job.get("address") or {}).get("postalAddress"),
                remote=bool(job.get("isRemote")),
                department=job.get("department") or job.get("team"),
                description=job.get("descriptionPlain") or job.get("descriptionHtml") or "",
                salary_text=salary,
                posted_at=job.get("publishedAt") or job.get("updatedAt"),
                apply_type="external",
                raw={"board": board, "data": job},
            )
        except Exception as e:
            log.warning(f"Ashby: skip malformed job: {e}")
            return None
