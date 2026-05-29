"""
Generic form filler used by both the Greenhouse and Lever adapters.

The strategy:
  1. Walk every visible <input>, <textarea>, <select>.
  2. For each one, look at its `name`, `id`, surrounding label / aria-label.
  3. Map to a candidate field using `infer_field_kind`.
  4. If we recognise it, fill from `CandidateData`.
  5. Otherwise, ask Claude for a short answer via the screening prompt.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:  # only loaded by type-checkers, not at runtime
    from playwright.async_api import Page  # noqa: F401

from app.config import settings
from app.utils.logger import log


@dataclass
class CandidateData:
    first_name: str
    last_name: str
    full_name: str
    email: str
    phone: str
    linkedin: str
    github: str
    portfolio: str
    current_location: str
    work_auth: str
    notice_period: str
    expected_ctc_lpa: float
    resume_path: Path
    cover_letter_path: Optional[Path]
    resume_json: dict
    job_title: str
    company: str

    @classmethod
    def from_settings(cls, **overrides) -> "CandidateData":
        full = settings.candidate_full_name.strip()
        first, *rest = full.split(" ", 1)
        last = rest[0] if rest else ""
        return cls(
            first_name=first,
            last_name=last,
            full_name=full,
            email=settings.candidate_email,
            phone=settings.candidate_phone,
            linkedin=settings.candidate_linkedin,
            github=settings.candidate_github,
            portfolio=settings.candidate_portfolio,
            current_location=settings.candidate_current_location,
            work_auth=settings.candidate_work_auth,
            notice_period=settings.candidate_notice_period,
            expected_ctc_lpa=settings.candidate_expected_ctc_lpa,
            **overrides,
        )


# Field-kind regex map. Order matters — first match wins.
_KIND_PATTERNS = [
    ("first_name", r"first[\s_-]?name|fname|given[\s_-]?name"),
    ("last_name", r"last[\s_-]?name|lname|family[\s_-]?name|surname"),
    ("full_name", r"^name$|full[\s_-]?name|your[\s_-]?name"),
    ("email", r"e[\s_-]?mail"),
    ("phone", r"phone|mobile|tel(?:ephone)?"),
    ("linkedin", r"linkedin"),
    ("github", r"github|portfolio[\s_-]?url|website|personal[\s_-]?site"),
    ("portfolio", r"portfolio|personal[\s_-]?website"),
    ("location", r"current[\s_-]?location|city|address|where.*based|location"),
    ("work_auth", r"work[\s_-]?auth|sponsorship|visa|right[\s_-]?to[\s_-]?work"),
    ("notice", r"notice[\s_-]?period|start[\s_-]?date|availability"),
    ("salary", r"salary|compensation|ctc|expected[\s_-]?pay"),
    ("relocate", r"relocate|relocation|willing.*move"),
    ("resume_upload", r"resume|cv"),
    ("cover_upload", r"cover[\s_-]?letter"),
]


def infer_field_kind(meta: str) -> Optional[str]:
    meta = (meta or "").lower()
    for kind, pat in _KIND_PATTERNS:
        if re.search(pat, meta):
            return kind
    return None


async def _label_for(page: "Page", handle) -> str:
    """Best-effort: combine name/id/aria-label/placeholder/label text."""
    bits = []
    for attr in ("name", "id", "aria-label", "placeholder"):
        v = await handle.get_attribute(attr)
        if v:
            bits.append(v)
    # Adjacent <label for=...>
    eid = await handle.get_attribute("id")
    if eid:
        try:
            label = await page.query_selector(f'label[for="{eid}"]')
            if label:
                t = (await label.inner_text()).strip()
                if t:
                    bits.append(t)
        except Exception:
            pass
    return " | ".join(bits)


async def _ask_llm_for_answer(question: str, cand: CandidateData) -> str:
    import json as _json

    from app.services.llm import llm  # lazy: avoid Anthropic import at module load

    prompt = llm.load_prompt("screening_answer").format(
        resume_json=_json.dumps(cand.resume_json, indent=2),
        job_title=cand.job_title,
        company=cand.company,
        question=question,
        expected_ctc_lpa=cand.expected_ctc_lpa,
        notice_period=cand.notice_period,
        current_location=cand.current_location,
        work_auth=cand.work_auth,
    )
    try:
        ans = llm.complete(
            system="You answer one application screening question, concisely.",
            user=prompt,
            max_tokens=200,
        )
        return ans.strip().strip('"').strip("'")
    except Exception as e:
        log.warning(f"LLM screening fallback for '{question[:60]}': {e}")
        return "Yes"


async def fill_form(page: "Page", cand: CandidateData) -> int:
    """Fill every visible input/textarea/select. Returns count filled."""
    filled = 0

    # Text inputs / textareas
    elements = await page.query_selector_all(
        "input:not([type=hidden]):not([type=submit]):not([type=button]), textarea"
    )
    for el in elements:
        try:
            visible = await el.is_visible()
            disabled = await el.is_disabled()
            if not visible or disabled:
                continue
            input_type = (await el.get_attribute("type") or "").lower()
            if input_type in ("file", "checkbox", "radio"):
                continue
            meta = await _label_for(page, el)
            kind = infer_field_kind(meta)
            value = _value_for_kind(kind, cand)
            if value is None:
                # Unknown — ask Claude
                if meta.strip():
                    value = await _ask_llm_for_answer(meta, cand)
                else:
                    continue
            await el.fill(str(value))
            filled += 1
            await asyncio.sleep(0.1)
        except Exception as e:
            log.debug(f"skip input: {e}")

    # Selects
    selects = await page.query_selector_all("select")
    for sel in selects:
        try:
            if not await sel.is_visible():
                continue
            meta = await _label_for(page, sel)
            kind = infer_field_kind(meta)
            opts = await sel.query_selector_all("option")
            opt_values = []
            for o in opts:
                v = await o.get_attribute("value")
                t = (await o.inner_text()).strip()
                if v:
                    opt_values.append((v, t))
            choice = _pick_option(kind, opt_values, cand)
            if choice:
                try:
                    await sel.select_option(value=choice[0])
                    filled += 1
                except Exception:
                    await sel.select_option(label=choice[1])
                    filled += 1
        except Exception as e:
            log.debug(f"skip select: {e}")

    # Radios / checkboxes for yes/no questions
    radios = await page.query_selector_all("input[type=radio], input[type=checkbox]")
    handled_groups: set[str] = set()
    for r in radios:
        try:
            if not await r.is_visible():
                continue
            name = await r.get_attribute("name") or ""
            if name in handled_groups:
                continue
            # Find the question label for the radio group
            label_text = await _label_for(page, r)
            value_attr = (await r.get_attribute("value") or "").lower()
            # default heuristic: select "yes" / "true" / "1"
            if value_attr in ("yes", "true", "1"):
                await r.check()
                handled_groups.add(name)
                filled += 1
                continue
            # otherwise ask LLM
            if label_text:
                ans = (await _ask_llm_for_answer(label_text, cand)).lower()
                if value_attr in ans or ans in value_attr:
                    await r.check()
                    handled_groups.add(name)
                    filled += 1
        except Exception as e:
            log.debug(f"skip radio: {e}")

    # File uploads
    file_inputs = await page.query_selector_all("input[type=file]")
    for f in file_inputs:
        try:
            meta = await _label_for(page, f)
            kind = infer_field_kind(meta)
            path: Optional[Path] = None
            if kind == "cover_upload" and cand.cover_letter_path:
                path = cand.cover_letter_path
            elif kind in ("resume_upload", None):
                path = cand.resume_path
            if path and Path(path).exists():
                await f.set_input_files(str(path))
                filled += 1
        except Exception as e:
            log.debug(f"skip file upload: {e}")

    return filled


def _value_for_kind(kind: Optional[str], cand: CandidateData) -> Optional[str]:
    if kind is None:
        return None
    return {
        "first_name": cand.first_name,
        "last_name": cand.last_name,
        "full_name": cand.full_name,
        "email": cand.email,
        "phone": cand.phone,
        "linkedin": cand.linkedin,
        "github": cand.github,
        "portfolio": cand.portfolio or cand.github,
        "location": cand.current_location,
        "work_auth": cand.work_auth,
        "notice": cand.notice_period,
        "salary": f"{cand.expected_ctc_lpa} LPA",
        "relocate": "Yes",
    }.get(kind)


def _pick_option(
    kind: Optional[str], opts: list[tuple[str, str]], cand: CandidateData
) -> Optional[tuple[str, str]]:
    if not opts:
        return None
    text_target = (_value_for_kind(kind, cand) or "").lower()
    if not text_target:
        # default: pick "Yes" if available, else first non-empty
        for v, t in opts:
            if t.strip().lower() in ("yes", "y"):
                return (v, t)
        return opts[0]
    # try exact, then substring
    for v, t in opts:
        if t.lower() == text_target:
            return (v, t)
    for v, t in opts:
        if text_target in t.lower() or t.lower() in text_target:
            return (v, t)
    return opts[0]
