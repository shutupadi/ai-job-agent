"""
Auto-apply driver.

Public entrypoint: `apply_to_job(job, resume_version, cover_letter)` (sync).
Runs Playwright internally with asyncio.

Per-source behaviour:
  - Greenhouse: most boards link to a hosted form at the job URL itself or
    at "<url>#app".  We navigate there, fill, submit.
  - Lever: postings link to https://jobs.lever.co/<co>/<id>/apply.

Safety:
  - HEADLESS_BROWSER controls visibility.
  - APPLY_MODE=approval short-circuits before submit.
  - RATE_LIMIT_SECONDS is applied by the caller, between jobs.
  - Screenshots on failure are stored under storage/screenshots/.
"""

from __future__ import annotations

import asyncio
import datetime as dt
from dataclasses import dataclass
from pathlib import Path

from playwright.async_api import (
    Page,
    Playwright,
    TimeoutError as PWTimeout,
    async_playwright,
)

from app.automation.form_filler import CandidateData, fill_form
from app.config import settings
from app.db import models
from app.utils.logger import log


CAPTCHA_PATTERNS = [
    "g-recaptcha",
    "hcaptcha",
    "cf-turnstile",
    "px-captcha",
    "Verify you are human",
]


@dataclass
class ApplyResult:
    success: bool
    error: str | None = None
    screenshot_path: str | None = None
    awaiting_approval: bool = False


def _screenshot_path(job_id: str, tag: str) -> Path:
    ts = dt.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    return Path(settings.storage_dir) / "screenshots" / f"{job_id[:8]}_{tag}_{ts}.png"


async def _has_captcha(page: Page) -> bool:
    html = (await page.content()).lower()
    return any(p.lower() in html for p in CAPTCHA_PATTERNS)


async def _click_submit(page: Page) -> bool:
    """Try several common submit-button selectors."""
    for sel in [
        'button[type="submit"]',
        'input[type="submit"]',
        'button:has-text("Submit application")',
        'button:has-text("Submit Application")',
        'button:has-text("Submit")',
        'button:has-text("Apply")',
        'button:has-text("Send application")',
    ]:
        try:
            btn = await page.query_selector(sel)
            if btn and await btn.is_visible() and not await btn.is_disabled():
                await btn.click()
                return True
        except Exception:
            continue
    return False


async def _looks_like_account_wall(page: Page) -> bool:
    """Detect sign-in / create-account gates (e.g. Workday) we won't bypass."""
    try:
        body = (await page.content()).lower()
    except Exception:
        return False
    needles = (
        "create account",
        "create an account",
        "sign in to apply",
        "use my last application",
        "to apply, you must",
        "sign in to your account",
    )
    return any(n in body for n in needles)


async def _confirm_submitted(page: Page) -> bool:
    """Heuristic: look for typical confirmation text after submit."""
    try:
        await page.wait_for_load_state("networkidle", timeout=15000)
    except PWTimeout:
        pass
    body = (await page.content()).lower()
    return any(
        kw in body
        for kw in (
            "thank you",
            "application received",
            "we've received your application",
            "your application has been submitted",
            "thanks for applying",
            "successfully submitted",
        )
    )


async def _run(
    pw: Playwright,
    job: models.Job,
    cand: CandidateData,
) -> ApplyResult:
    browser = await pw.chromium.launch(headless=settings.headless_browser)
    context = await browser.new_context(
        user_agent=(
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1366, "height": 900},
        locale="en-US",
    )
    page = await context.new_page()
    error: str | None = None
    screenshot: str | None = None
    success = False
    awaiting_approval = False

    try:
        target = job.url
        if job.source == "greenhouse" and "#app" not in target:
            target = target.rstrip("/") + "#app"
        log.info(f"Navigating to {target}")
        await page.goto(target, timeout=45000, wait_until="domcontentloaded")
        await asyncio.sleep(2)

        if await _has_captcha(page):
            shot = _screenshot_path(job.id, "captcha")
            await page.screenshot(path=str(shot), full_page=True)
            return ApplyResult(
                success=False,
                error="captcha-detected",
                screenshot_path=str(shot),
            )

        # If site shows an "Apply" button before the form, click it.
        for sel in [
            'a:has-text("Apply for this job")',
            'a:has-text("Apply for this Job")',
            'button:has-text("Apply now")',
            'a:has-text("Apply now")',
        ]:
            try:
                btn = await page.query_selector(sel)
                if btn and await btn.is_visible():
                    await btn.click()
                    await asyncio.sleep(2)
                    break
            except Exception:
                pass

        filled = await fill_form(page, cand)
        log.info(f"Filled {filled} fields on {job.company} – {job.title}")

        if filled == 0:
            # No fillable form. If this is a login/account wall (common on
            # Workday), hand it back for manual completion instead of marking a
            # hard failure — we never create accounts or bypass auth.
            if (
                "myworkdayjobs.com" in (job.url or "")
                or "oraclecloud.com" in (job.url or "")
                or await _looks_like_account_wall(page)
            ):
                shot = _screenshot_path(job.id, "login-wall")
                await page.screenshot(path=str(shot), full_page=True)
                return ApplyResult(
                    success=False,
                    awaiting_approval=True,
                    error="account-or-login-required",
                    screenshot_path=str(shot),
                )
            shot = _screenshot_path(job.id, "noform")
            await page.screenshot(path=str(shot), full_page=True)
            return ApplyResult(
                success=False,
                error="no-fillable-form",
                screenshot_path=str(shot),
            )

        if settings.apply_mode.lower() == "approval":
            shot = _screenshot_path(job.id, "awaiting-approval")
            await page.screenshot(path=str(shot), full_page=True)
            return ApplyResult(
                success=False,
                awaiting_approval=True,
                screenshot_path=str(shot),
            )

        clicked = await _click_submit(page)
        if not clicked:
            shot = _screenshot_path(job.id, "nosubmit")
            await page.screenshot(path=str(shot), full_page=True)
            return ApplyResult(
                success=False,
                error="submit-button-not-found",
                screenshot_path=str(shot),
            )

        success = await _confirm_submitted(page)
        if not success:
            shot = _screenshot_path(job.id, "noconfirm")
            await page.screenshot(path=str(shot), full_page=True)
            return ApplyResult(
                success=False,
                error="no-confirmation",
                screenshot_path=str(shot),
            )

        screenshot = str(_screenshot_path(job.id, "submitted"))
        await page.screenshot(path=screenshot, full_page=True)

    except Exception as e:
        error = f"{type(e).__name__}: {e}"
        try:
            shot = _screenshot_path(job.id, "exception")
            await page.screenshot(path=str(shot), full_page=True)
            screenshot = str(shot)
        except Exception:
            pass
        log.exception(f"Auto-apply error on {job.url}: {error}")
    finally:
        await context.close()
        await browser.close()

    return ApplyResult(
        success=success,
        error=error,
        screenshot_path=screenshot,
        awaiting_approval=awaiting_approval,
    )


async def _apply_async(job: models.Job, cand: CandidateData) -> ApplyResult:
    async with async_playwright() as pw:
        return await _run(pw, job, cand)


def apply_to_job(
    job: models.Job,
    resume_version: models.ResumeVersion,
    cover_letter: models.CoverLetter | None,
) -> ApplyResult:
    cand = CandidateData.from_settings(
        resume_path=Path(resume_version.pdf_path),
        cover_letter_path=Path(cover_letter.pdf_path) if cover_letter and cover_letter.pdf_path else None,
        resume_json=resume_version.json_payload,
        job_title=job.title,
        company=job.company,
    )
    return asyncio.run(_apply_async(job, cand))
