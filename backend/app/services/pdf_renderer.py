"""
PDF renderers using reportlab.

Two outputs:
  - resume PDF  (single-page-friendly layout)
  - cover letter PDF
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)

INK = HexColor("#111827")
MUTED = HexColor("#4b5563")
ACCENT = HexColor("#1f2937")


def _styles():
    base = getSampleStyleSheet()
    name = ParagraphStyle(
        "name",
        parent=base["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
        textColor=INK,
        spaceAfter=2,
    )
    contact = ParagraphStyle(
        "contact",
        parent=base["Normal"],
        fontName="Helvetica",
        fontSize=9.5,
        leading=12,
        textColor=MUTED,
        spaceAfter=6,
    )
    section = ParagraphStyle(
        "section",
        parent=base["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=14,
        textColor=ACCENT,
        spaceBefore=8,
        spaceAfter=2,
        alignment=TA_LEFT,
    )
    body = ParagraphStyle(
        "body",
        parent=base["Normal"],
        fontName="Helvetica",
        fontSize=9.5,
        leading=12.5,
        textColor=INK,
    )
    bullet = ParagraphStyle(
        "bullet",
        parent=body,
        leftIndent=10,
        bulletIndent=0,
        spaceAfter=1,
    )
    role = ParagraphStyle(
        "role",
        parent=body,
        fontName="Helvetica-Bold",
        textColor=INK,
        spaceBefore=4,
        spaceAfter=0,
    )
    sub = ParagraphStyle(
        "sub",
        parent=body,
        fontName="Helvetica-Oblique",
        textColor=MUTED,
        spaceAfter=2,
    )
    return name, contact, section, body, bullet, role, sub


def _esc(s: Any) -> str:
    return str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_resume_pdf(resume: dict, out_path: Path) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    name_s, contact_s, sec_s, body_s, bul_s, role_s, sub_s = _styles()
    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=LETTER,
        leftMargin=0.55 * inch,
        rightMargin=0.55 * inch,
        topMargin=0.55 * inch,
        bottomMargin=0.55 * inch,
        title=f"{resume.get('name','Resume')} – Resume",
    )

    flow = []

    # Header
    flow.append(Paragraph(_esc(resume.get("name", "")), name_s))
    contact_bits = [
        _esc(resume.get("email", "")),
        _esc(resume.get("phone", "")),
    ]
    links = resume.get("links") or {}
    for k in ("linkedin", "github", "portfolio"):
        v = links.get(k)
        if v:
            contact_bits.append(_esc(v))
    flow.append(Paragraph(" • ".join([b for b in contact_bits if b]), contact_s))
    flow.append(HRFlowable(width="100%", thickness=0.5, color=MUTED, spaceBefore=2, spaceAfter=4))

    # Summary
    if resume.get("summary"):
        flow.append(Paragraph("Summary", sec_s))
        flow.append(Paragraph(_esc(resume["summary"]), body_s))

    # Skills
    skills = resume.get("skills") or {}
    if skills:
        flow.append(Paragraph("Skills", sec_s))
        if isinstance(skills, dict):
            for k, vals in skills.items():
                if not vals:
                    continue
                line = f"<b>{_esc(k.title())}:</b> " + ", ".join(_esc(v) for v in vals)
                flow.append(Paragraph(line, body_s))
        elif isinstance(skills, list):
            flow.append(Paragraph(", ".join(_esc(v) for v in skills), body_s))

    # Experience
    exps = resume.get("experience") or []
    if exps:
        flow.append(Paragraph("Experience", sec_s))
        for e in exps:
            flow.append(
                Paragraph(
                    f"<b>{_esc(e.get('title',''))}</b> — {_esc(e.get('company',''))}",
                    role_s,
                )
            )
            sub = " | ".join(
                _esc(x)
                for x in [
                    e.get("location"),
                    f"{e.get('start','')} – {e.get('end','')}".strip(" –"),
                ]
                if x
            )
            if sub:
                flow.append(Paragraph(sub, sub_s))
            for b in e.get("bullets") or []:
                flow.append(Paragraph(f"• {_esc(b)}", bul_s))

    # Projects
    projs = resume.get("projects") or []
    if projs:
        flow.append(Paragraph("Projects", sec_s))
        for p in projs:
            stack = ", ".join(_esc(s) for s in (p.get("stack") or []))
            head = f"<b>{_esc(p.get('name',''))}</b>"
            if stack:
                head += f" — <i>{stack}</i>"
            flow.append(Paragraph(head, role_s))
            for b in p.get("bullets") or []:
                flow.append(Paragraph(f"• {_esc(b)}", bul_s))

    # Education
    edus = resume.get("education") or []
    if edus:
        flow.append(Paragraph("Education", sec_s))
        for ed in edus:
            head = f"<b>{_esc(ed.get('degree',''))}</b> — {_esc(ed.get('school',''))}"
            flow.append(Paragraph(head, role_s))
            sub = " | ".join(
                _esc(x)
                for x in [
                    f"{ed.get('start','')} – {ed.get('end','')}".strip(" –"),
                    ed.get("details"),
                ]
                if x
            )
            if sub:
                flow.append(Paragraph(sub, sub_s))

    # Achievements
    achs = resume.get("achievements") or []
    if achs:
        flow.append(Paragraph("Achievements", sec_s))
        for a in achs:
            flow.append(Paragraph(f"• {_esc(a)}", bul_s))

    flow.append(Spacer(1, 4))
    doc.build(flow)
    return out_path


def render_cover_letter_pdf(text: str, candidate_name: str, out_path: Path) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    base = getSampleStyleSheet()
    body = ParagraphStyle(
        "body",
        parent=base["Normal"],
        fontName="Helvetica",
        fontSize=10.5,
        leading=14,
        textColor=INK,
        spaceAfter=8,
    )
    name_style = ParagraphStyle(
        "n",
        parent=base["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=12,
        textColor=INK,
        spaceAfter=10,
    )

    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=LETTER,
        leftMargin=0.9 * inch,
        rightMargin=0.9 * inch,
        topMargin=0.9 * inch,
        bottomMargin=0.9 * inch,
        title=f"{candidate_name} – Cover Letter",
    )
    flow = [Paragraph(_esc(candidate_name), name_style)]
    for para in text.strip().split("\n\n"):
        flow.append(Paragraph(_esc(para).replace("\n", "<br/>"), body))
    doc.build(flow)
    return out_path
