"""
LinkedIn logged-in DISCOVERY runner (local, attended) — NEVER applies.

Replaces the old `linkedin_apply.py`. The user asked to drop fully-automated
LinkedIn applications and instead use LinkedIn purely to *discover and filter*
relevant jobs with the richer data a logged-in session exposes.

What it does:
  1. Opens a real Chromium window using a persistent profile
     (storage/linkedin_profile) so your login survives across runs. On first
     run, log in manually; it waits up to ~5 minutes.
  2. Collects job ids from your **Recommended** jobs + a few keyword/location
     searches (newest first, last 24h).
  3. Opens each posting, extracts title / company / location / full JD.
  4. Runs them through the SAME geo + fresher experience filters as the pipeline.
  5. Upserts the survivors into the DB as source="linkedin", auto_apply=False.
  6. Optionally ranks the new jobs immediately (`--rank`).

It does NOT click Apply, fill forms, or submit anything — discovery only.

DB note: like the (now removed) apply runner, this is a LOCAL tool. DATABASE_URL
normally points at the docker-compose host "db" which only resolves inside the
compose network, so we rewrite it to localhost (compose publishes 5432). A
preflight check fails fast — before opening the browser — if the DB is down or
the schema is behind.

CAUTION: scraping LinkedIn, even while logged in and even without applying, is
against its User Agreement (§8.2). Volume is capped (LINKEDIN_DISCOVER_MAX) and
rate-limited; use sparingly for your own job hunt.

    python -m app.automation.linkedin_discover            # headful, recommended + searches
    python -m app.automation.linkedin_discover --rank     # also rank new jobs now
    python -m app.automation.linkedin_discover --max 25 --keywords "SDE,Backend"
"""

from __future__ import annotations

import argparse
import asyncio
import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import quote_plus

from playwright.async_api import Page, async_playwright
from sqlalchemy import create_engine, inspect as sa_inspect, text
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.services import experience_filter, geo_filter
from app.services.dedupe import upsert_jobs
from app.sources.base import RawJob
from app.utils.logger import log


# ── Local DB access (db→localhost rewrite + preflight) ───────────────
def _local_db_url() -> str:
    url = settings.database_url
    if "@db:" in url:
        url = url.replace("@db:", "@localhost:")
    elif "@db/" in url:
        url = url.replace("@db/", "@localhost/")
    return url


_engine = None
_SessionLocal = None


def _get_engine():
    global _engine
    if _engine is None:
        url = _local_db_url()
        kwargs: dict = {"future": True, "pool_pre_ping": True}
        if not url.startswith("sqlite"):
            kwargs.update({"pool_size": 5, "max_overflow": 10})
        _engine = create_engine(url, **kwargs)
    return _engine


def _session_factory():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            bind=_get_engine(), autoflush=False, autocommit=False, expire_on_commit=False
        )
    return _SessionLocal


@contextmanager
def session_scope():
    db = _session_factory()()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


_REQUIRED_JOB_COLUMNS = {"auto_apply", "applied_manually_at"}


def _db_preflight() -> Optional[str]:
    """Return None if the DB is reachable AND migrated, else an error string."""
    try:
        with session_scope() as db:
            db.execute(text("SELECT 1"))
        cols = {c["name"] for c in sa_inspect(_get_engine()).get_columns("jobs")}
        missing = _REQUIRED_JOB_COLUMNS - cols
        if missing:
            return (
                f"database schema is out of date — jobs table is missing "
                f"{sorted(missing)}. Apply migrations with:  alembic upgrade head"
            )
        return None
    except Exception as e:  # noqa: BLE001
        return str(e)


# ── options ──────────────────────────────────────────────────────────
@dataclass
class Opts:
    max: int
    headless: bool
    rank: bool
    recommended: bool
    keywords: List[str] = field(default_factory=list)
    locations: List[str] = field(default_factory=list)


# ── DOM helpers ───────────────────────────────────────────────────────
async def _text(scope, *selectors: str) -> Optional[str]:
    for sel in selectors:
        try:
            el = await scope.query_selector(sel)
            if el:
                t = (await el.inner_text()).strip()
                if t:
                    return t
        except Exception:
            continue
    return None


async def _ensure_logged_in(page: Page) -> bool:
    """Open LinkedIn; wait (up to ~5 min) for the user to log in if needed."""
    try:
        await page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        log.warning(f"LinkedIn navigation issue: {e}")
    printed = False
    for _ in range(150):  # 150 × 2s = 5 min
        try:
            url = page.url
            if (
                "/feed" in url
                or await page.query_selector("#global-nav")
                or await page.query_selector("input.search-global-typeahead__input")
            ):
                return True
        except Exception:
            pass
        if not printed:
            log.info("➡️  Please LOG IN to LinkedIn in the opened window. Waiting…")
            printed = True
        await asyncio.sleep(2)
    return False


def _search_url(keyword: str, location: Optional[str]) -> str:
    q = f"https://www.linkedin.com/jobs/search/?keywords={quote_plus(keyword)}"
    if location:
        q += f"&location={quote_plus(location)}"
    # f_TPR=r86400 -> posted in last 24h; sortBy=DD -> newest first
    q += "&f_TPR=r86400&sortBy=DD"
    return q


async def _collect_job_ids(page: Page, want: int) -> List[str]:
    ids: List[str] = []
    seen: set[str] = set()
    for _ in range(10):
        try:
            hrefs = await page.eval_on_selector_all(
                "a[href*='/jobs/view/']",
                "els => els.map(e => e.getAttribute('href'))",
            )
        except Exception:
            hrefs = []
        for h in hrefs or []:
            m = re.search(r"/jobs/view/(\d+)", h or "")
            if m and m.group(1) not in seen:
                seen.add(m.group(1))
                ids.append(m.group(1))
        try:
            data_ids = await page.eval_on_selector_all(
                "[data-job-id], [data-occludable-job-id]",
                "els => els.map(e => e.getAttribute('data-job-id') || e.getAttribute('data-occludable-job-id'))",
            )
        except Exception:
            data_ids = []
        for d in data_ids or []:
            if d and str(d).isdigit() and d not in seen:
                seen.add(d)
                ids.append(d)
        if len(ids) >= want:
            break
        try:
            await page.mouse.wheel(0, 2600)
        except Exception:
            pass
        await asyncio.sleep(1.3)
    return ids[:want]


async def _extract_job(page: Page, jid: str) -> Optional[RawJob]:
    """Open a job posting and scrape title/company/location/JD (no apply)."""
    url = f"https://www.linkedin.com/jobs/view/{jid}/"
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
    except Exception as e:
        log.debug(f"nav {jid}: {e}")
        return None
    await asyncio.sleep(1.1)
    # Expand the "see more" JD toggle if present.
    try:
        btn = await page.query_selector(
            "button.show-more-less-html__button, button[aria-label*='see more']"
        )
        if btn and await btn.is_visible():
            await btn.click()
            await asyncio.sleep(0.4)
    except Exception:
        pass

    title = await _text(
        page,
        "h1.job-details-jobs-unified-top-card__job-title",
        ".job-details-jobs-unified-top-card__job-title",
        "h1.jobs-unified-top-card__job-title",
        "h1.t-24",
        "h1",
    )
    company = await _text(
        page,
        ".job-details-jobs-unified-top-card__company-name a",
        ".job-details-jobs-unified-top-card__company-name",
        ".jobs-unified-top-card__company-name",
        "a.app-aware-link[href*='/company/']",
    )
    location = await _text(
        page,
        ".job-details-jobs-unified-top-card__primary-description-container",
        ".jobs-unified-top-card__primary-description",
        ".jobs-unified-top-card__bullet",
    )
    desc = await _text(
        page,
        "#job-details",
        ".jobs-description__content",
        "article.jobs-description__container",
        ".jobs-box__html-content",
        ".jobs-description-content__text",
    )
    if not title or not company:
        log.debug(f"skip {jid}: missing title/company")
        return None
    blob = f"{location or ''} {desc or ''}".lower()
    remote = "remote" in (location or "").lower() or "work from home" in blob
    return RawJob(
        source="linkedin",
        external_id=str(jid),
        url=url,
        title=title,
        company=company,
        location=location,
        remote=remote,
        description=(desc or "")[:8000],
        auto_apply=False,  # discovery only — user applies on LinkedIn by hand
        raw={"linkedin_job_id": jid},
    )


# ── main flow ──────────────────────────────────────────────────────────
async def run(opts: Opts) -> None:
    db_err = _db_preflight()
    if db_err:
        log.error(
            "Cannot reach the database at %s — is the Postgres container running?\n"
            "  Start it with:  docker compose up -d db\n"
            "  (Local runner connects via localhost:5432, which compose publishes.)\n"
            "  Underlying error: %s",
            _local_db_url(),
            db_err,
        )
        return

    settings.linkedin_profile_dir.mkdir(parents=True, exist_ok=True)
    log.warning(
        "LinkedIn DISCOVERY starting — discovery only, it NEVER applies. "
        "Note: scraping LinkedIn is against its ToS; keeping volume polite. max=%s",
        opts.max,
    )

    raws: List[RawJob] = []
    async with async_playwright() as pw:
        context = await pw.chromium.launch_persistent_context(
            user_data_dir=str(settings.linkedin_profile_dir),
            headless=opts.headless,
            viewport={"width": 1366, "height": 900},
            accept_downloads=False,
        )
        page = context.pages[0] if context.pages else await context.new_page()

        if not await _ensure_logged_in(page):
            log.error("Not logged in to LinkedIn after waiting — aborting.")
            await context.close()
            return
        log.info("LinkedIn session ready.")

        ids: List[str] = []

        # 1) Recommended jobs (the richer logged-in signal).
        if opts.recommended:
            try:
                await page.goto(
                    "https://www.linkedin.com/jobs/collections/recommended/",
                    wait_until="domcontentloaded",
                    timeout=60000,
                )
                await asyncio.sleep(2.5)
                got = await _collect_job_ids(page, want=opts.max)
                ids += got
                log.info(f"[recommended] collected {len(got)} ids")
            except Exception as e:
                log.warning(f"recommended collect failed: {e}")

        # 2) Keyword/location searches (newest first, last 24h).
        for kw in opts.keywords[:5]:
            if len(ids) >= opts.max * 2:
                break
            for loc in (opts.locations[:3] or [None]):
                try:
                    await page.goto(_search_url(kw, loc), wait_until="domcontentloaded", timeout=60000)
                    await asyncio.sleep(2.0)
                    got = await _collect_job_ids(page, want=opts.max)
                    ids += got
                    log.info(f"[{kw} @ {loc or 'any'}] collected {len(got)} ids")
                except Exception as e:
                    log.warning(f"search '{kw}'@'{loc}' failed: {e}")

        # De-dup ids, preserve order, cap at max, then scrape each JD.
        seen: set[str] = set()
        uniq = [i for i in ids if not (i in seen or seen.add(i))]
        log.info(f"Collected {len(uniq)} unique job ids; extracting up to {opts.max}…")
        for jid in uniq[: opts.max]:
            raw = await _extract_job(page, jid)
            if raw:
                raws.append(raw)
            await asyncio.sleep(1.4)  # polite pacing

        await context.close()

    log.info(f"Extracted {len(raws)} LinkedIn jobs; applying geo + experience filters…")
    kept, geo_dropped = geo_filter.filter_rawjobs(raws)
    kept, exp_dropped = experience_filter.filter_rawjobs(kept)
    log.info(
        f"After filters: kept {len(kept)} "
        f"(geo_dropped={geo_dropped}, exp_dropped={exp_dropped})"
    )

    with session_scope() as db:
        new_jobs, _ = upsert_jobs(db, kept)
        new_count = len(new_jobs)
    log.info(f"Ingested {new_count} new LinkedIn jobs into the DB (source=linkedin).")

    if opts.rank and new_count:
        from app.services.pipeline import rank_new_jobs

        n = rank_new_jobs(settings.max_ranks_per_run)
        log.info(f"Ranked {n} newly ingested jobs.")
    elif new_count:
        log.info("Run with --rank to score them now, or wait for the next pipeline run.")

    log.info("LinkedIn discovery done. Review the shortlist in the dashboard.")


# ── CLI ──────────────────────────────────────────────────────────────
def _build_opts(args) -> Opts:
    kws = (
        [k.strip() for k in args.keywords.split(",") if k.strip()]
        if args.keywords
        else settings.keywords
    )
    locs = (
        [l.strip() for l in args.locations.split(",") if l.strip()]
        if args.locations
        else (settings.locations or ["India"])
    )
    return Opts(
        max=args.max or settings.linkedin_discover_max,
        headless=args.headless,
        rank=args.rank,
        recommended=not args.no_recommended,
        keywords=kws,
        locations=locs,
    )


def main() -> None:
    p = argparse.ArgumentParser(
        description="LinkedIn logged-in DISCOVERY (scrapes jobs into the DB for ranking; never applies)."
    )
    p.add_argument("--max", type=int, default=0, help="Max jobs to ingest (default: LINKEDIN_DISCOVER_MAX).")
    p.add_argument("--keywords", type=str, default="", help="Comma-separated; default: KEYWORDS from .env.")
    p.add_argument("--locations", type=str, default="", help="Comma-separated; default: LOCATIONS from .env.")
    p.add_argument("--headless", action="store_true", help="Run headless (only after you've logged in once).")
    p.add_argument("--rank", action="store_true", help="Rank newly ingested jobs immediately (uses LLM quota).")
    p.add_argument("--no-recommended", action="store_true", help="Skip the Recommended jobs page.")
    args = p.parse_args()
    asyncio.run(run(_build_opts(args)))


if __name__ == "__main__":
    main()
