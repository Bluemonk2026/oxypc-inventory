"""Renders the Technical/Functional Specification documents as presentable PDFs.

Content stays hand-maintained in routers/qa_uat.py; this module only handles layout.
"""
from __future__ import annotations

import re
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    ListFlowable, ListItem, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

_NAVY = colors.HexColor("#1F3864")
_ACCENT = colors.HexColor("#2E75B6")
_LIGHT = colors.HexColor("#EEF3F8")
_MUTED = colors.HexColor("#5A6472")

_SECTION_RE = re.compile(r"^\d+\.\s+(.+)$")


def _styles():
    ss = getSampleStyleSheet()
    ss.add(ParagraphStyle("DocTitle", parent=ss["Title"], fontName="Helvetica-Bold",
                           fontSize=22, textColor=_NAVY, spaceAfter=6))
    ss.add(ParagraphStyle("DocSubtitle", parent=ss["Normal"], fontName="Helvetica",
                           fontSize=11, textColor=_MUTED, spaceAfter=2))
    ss.add(ParagraphStyle("Section", parent=ss["Heading1"], fontName="Helvetica-Bold",
                           fontSize=14, textColor=colors.white, spaceBefore=16, spaceAfter=8,
                           backColor=_NAVY, borderPadding=(6, 6, 6, 6), leading=18))
    ss.add(ParagraphStyle("Body", parent=ss["Normal"], fontName="Helvetica",
                           fontSize=9.5, leading=14, spaceAfter=4))
    ss.add(ParagraphStyle("SpecBullet", parent=ss["Normal"], fontName="Helvetica",
                           fontSize=9.5, leading=13.5))
    ss.add(ParagraphStyle("Footer", parent=ss["Normal"], fontName="Helvetica-Oblique",
                           fontSize=8, textColor=_MUTED))
    return ss


def _parse_sections(raw: str):
    """Split the plain-text spec body into (title, [lines]) sections on '1. TITLE' headers.

    Drops the trailing "This document is generated..." closer baked into the source
    text, since the PDF renders its own footer with the same message.
    """
    body = raw.split("This document is generated on demand")[0]
    lines = body.strip("\n").split("\n")
    sections = []
    current_title = None
    current_lines = []
    for line in lines:
        m = _SECTION_RE.match(line.strip())
        if m and line.strip()[0].isdigit():
            if current_title:
                sections.append((current_title, current_lines))
            current_title = m.group(1).strip()
            current_lines = []
            continue
        if set(line.strip()) in ({"-"}, {"="}):
            continue
        if current_title is None:
            continue
        if not line.strip() and current_lines and current_lines[-1] == "":
            continue
        current_lines.append(line.rstrip())
    if current_title:
        sections.append((current_title, current_lines))
    return sections


def _render_section_body(lines, styles, story):
    bullets = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if bullets:
                story.append(ListFlowable(
                    [ListItem(Paragraph(b, styles["SpecBullet"]), leftIndent=6) for b in bullets],
                    bulletType="bullet", start="circle", leftIndent=14, spaceBefore=2, spaceAfter=6,
                ))
                bullets = []
            continue
        if stripped.startswith("- ") or re.match(r"^[a-z]\.\s", stripped) or re.match(r"^\d+\.\s", stripped):
            bullets.append(stripped.lstrip("- "))
        else:
            if bullets:
                story.append(ListFlowable(
                    [ListItem(Paragraph(b, styles["SpecBullet"]), leftIndent=6) for b in bullets],
                    bulletType="bullet", start="circle", leftIndent=14, spaceBefore=2, spaceAfter=6,
                ))
                bullets = []
            story.append(Paragraph(stripped, styles["Body"]))
    if bullets:
        story.append(ListFlowable(
            [ListItem(Paragraph(b, styles["SpecBullet"]), leftIndent=6) for b in bullets],
            bulletType="bullet", start="circle", leftIndent=14, spaceBefore=2, spaceAfter=6,
        ))


def build_spec_pdf(*, doc_code: str, title: str, subtitle: str, raw_content: str, generated_on: str) -> bytes:
    """Renders a specification document (TSD/FSD) into a styled PDF and returns the bytes."""
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=LETTER,
        leftMargin=0.75 * inch, rightMargin=0.75 * inch,
        topMargin=0.75 * inch, bottomMargin=0.75 * inch,
        title=title,
    )
    styles = _styles()
    story = []

    # Cover block
    story.append(Table(
        [[Paragraph(title, styles["DocTitle"])]],
        colWidths=[6.9 * inch],
        style=TableStyle([
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
        ]),
    ))
    story.append(Paragraph(subtitle, styles["DocSubtitle"]))
    story.append(Paragraph(f"Document code: {doc_code} &nbsp;|&nbsp; Generated: {generated_on}", styles["DocSubtitle"]))
    story.append(Spacer(1, 4))
    story.append(Table([[""]], colWidths=[6.9 * inch], rowHeights=[2],
                        style=TableStyle([("BACKGROUND", (0, 0), (-1, -1), _ACCENT)])))
    story.append(Spacer(1, 14))

    sections = _parse_sections(raw_content)
    closing_lines = []
    for title_line, lines in sections:
        story.append(Paragraph(title_line, styles["Section"]))
        _render_section_body(lines, styles, story)

    story.append(Spacer(1, 10))
    story.append(Table([[""]], colWidths=[6.9 * inch], rowHeights=[0.75],
                        style=TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#CCCCCC"))])))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        "Generated on demand from the OxyPC Inventory QA Dashboard — reflects the live "
        "codebase at the time of download. Regenerate after any major change.",
        styles["Footer"],
    ))

    doc.build(story)
    return buf.getvalue()
