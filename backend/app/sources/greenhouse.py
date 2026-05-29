"""
Greenhouse public job-board API.

Endpoint:  https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true

This endpoint is intentionally public and meant to be consumed by third
parties — no scraping, no terms violation. We rate-limit ourselves anyway.
"""

from __future__ import annotations

import time
from typing import Iterable, List

import httpx
from bs4 import BeautifulSoup

from app.config import settings
from app.sources.base import RawJob
from app.utils.logger import log

API = "https://boards-api.greenhouse.io/v1/boards/{board}/jobs"


def _strip_html(html: str) -> str:
    if not html:
        return ""
    return BeautifulSoup(html, "lxml").get_text("\n").strip()


class GreenhouseSource:
    name = "greenhouse"

    def __init__(self, boards: List[str] | None = None):
        self.boards = boards or settings.greenhouse_boards

    def fetch(self) -> Iterable[RawJob]:
        if not self.boards:
            log.info("Greenhouse: no boards configured, skipping")
            return []
        results: List[RawJob] = []
        with httpx.Client(timeout=20, follow_redirects=True) as client:
            for board in self.boards:
                board = board.strip()
                if not board:
                    continue
                url = API.format(board=board)
                try:
                    r = client.get(url, params={"content": "true"})
                    r.raise_for_status()
                except Exception as e:
                    log.warning(f"Greenhouse '{board}' fetch failed: {e}")
                    continue
                data = r.json()
                for job in data.get("jobs", []):
                    raw = self._convert(board, job)
                    if raw:
                        results.append(raw)
                # Be polite
                time.sleep(0.5)
        log.info(f"Greenhouse: pulled {len(results)} postings from {len(self.boards)} boards")
        return results

    def _convert(self, board: str, job: dict) -> RawJob | None:
        try:
            location = (job.get("location") or {}).get("name")
            content = _strip_html(job.get("content", ""))
            remote = "remote" in (location or "").lower() or "remote" in content.lower()[:600]
            department = None
            depts = job.get("departments") or []
            if depts:
                department = depts[0].get("name")
            return RawJob(
                source=self.name,
                external_id=str(job["id"]),
                url=job.get("absolute_url", ""),
                title=job.get("title", "").strip(),
                company=board.replace("-", " ").title(),
                location=location,
                remote=remote,
                department=department,
                description=content,
                posted_at=job.get("updated_at"),
                raw={"board": board, "data": job},
            )
        except Exception as e:
            log.warning(f"Greenhouse: skip malformed job: {e}")
            return None
