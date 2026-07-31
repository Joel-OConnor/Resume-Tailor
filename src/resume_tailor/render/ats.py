"""The ATS-safe layout: one column, standard headings, no tables anywhere.

This is the file you submit through an Applicant Tracking System. Every choice here exists to
survive a parser: a single top-to-bottom text flow, real bullet lists, contact details in the
body rather than the header region, and no graphics. See ``reference/ATS-PLAYBOOK.md``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, assert_never

from docx import Document as new_docx
from docx.shared import Pt

from resume_tailor.documents.blocks import (
    Bullet,
    Entry,
    HeaderLine,
    Meta,
    Name,
    Paragraph,
    Section,
    SkillLine,
    Span,
)
from resume_tailor.render.docx_common import add_spans, set_bottom_border, set_indent, set_spacing
from resume_tailor.render.html_common import page, spans_to_html

if TYPE_CHECKING:
    from pathlib import Path

    from docx.document import Document as DocxDocument
    from docx.text.paragraph import Paragraph as DocxParagraph

    from resume_tailor.documents.blocks import Block, Document

__all__ = ["render_docx", "render_html"]

FONT = "Calibri"
BODY_PT = 10.0
PROSE_PT = 10.5
NAME_PT = 20.0
SECTION_PT = 12.0
ENTRY_PT = 11.0
MUTED = "444444"

# Absolute, so Word and the browser agree. GAP_PT is the space ABOVE each block: Word sums
# adjacent spacing while CSS collapses it, so the whole gap lives in one property on both sides.
LINE_PT = 13.5
GAP_PT = {
    "name": 0.0,
    "header": 1.0,
    "section": 12.0,
    "entry": 8.0,
    "meta": 1.0,
    "skill": 1.0,
    "bullet": 1.0,
    "para": 5.0,
}
BULLET_INDENT_IN = 0.25
BULLET_HANGING_IN = 0.15


def render_docx(document: Document, out: Path) -> None:
    """Write ``document`` as a single-column, parser-friendly ``.docx``."""
    docx = new_docx()
    _configure(docx)
    for block in document.blocks:
        _add_block(docx, block)
    docx.save(str(out))


def _configure(docx: DocxDocument) -> None:
    normal = docx.styles["Normal"].font
    normal.name = FONT
    normal.size = Pt(PROSE_PT)
    for section in docx.sections:
        section.top_margin = section.bottom_margin = Pt(0.6 * 72)
        section.left_margin = section.right_margin = Pt(0.7 * 72)


def _add_block(docx: DocxDocument, block: Block) -> None:
    match block:
        case Name(spans):
            paragraph = _paragraph(docx, "name")
            add_spans(paragraph, spans, font=FONT, size=NAME_PT, bold=True)
        case HeaderLine(spans):
            paragraph = _paragraph(docx, "header")
            add_spans(paragraph, spans, font=FONT, size=BODY_PT, color=MUTED)
        case Section(title):
            paragraph = _paragraph(docx, "section")
            add_spans(paragraph, (Span(title.upper()),), font=FONT, size=SECTION_PT, bold=True)
            set_bottom_border(paragraph)
        case Entry(spans):
            paragraph = _paragraph(docx, "entry")
            add_spans(paragraph, spans, font=FONT, size=ENTRY_PT, bold=True)
        case Meta(spans):
            paragraph = _paragraph(docx, "meta")
            add_spans(paragraph, spans, font=FONT, size=BODY_PT, italic=True, color=MUTED)
        case SkillLine(label, items):
            paragraph = _paragraph(docx, "skill")
            add_spans(paragraph, (Span(f"{label}: "),), font=FONT, size=BODY_PT, bold=True)
            add_spans(paragraph, items, font=FONT, size=BODY_PT)
        case Bullet(spans):
            paragraph = _paragraph(docx, "bullet", style="List Bullet")
            set_indent(paragraph, left=BULLET_INDENT_IN, right=0, hanging=BULLET_HANGING_IN)
            add_spans(paragraph, spans, font=FONT, size=BODY_PT)
        case Paragraph(spans):
            paragraph = _paragraph(docx, "para")
            add_spans(paragraph, spans, font=FONT, size=PROSE_PT)
        case _:  # pragma: no cover - mypy proves the block union is exhaustive
            assert_never(block)


def _paragraph(docx: DocxDocument, kind: str, *, style: str | None = None) -> DocxParagraph:
    paragraph = docx.add_paragraph(style=style)
    set_spacing(paragraph, before=GAP_PT[kind], line=LINE_PT)
    return paragraph


CSS = f"""
@page {{ size: Letter; margin: 0.6in 0.7in; }}
* {{ box-sizing: border-box; }}
/* Every gap is a margin-TOP and every bottom margin is 0, so CSS collapsing and Word's additive
   spacing produce the same number. line-height is absolute for the same reason. */
body {{ font-family: Calibri, Helvetica, Arial, sans-serif; font-size: {PROSE_PT}pt;
        line-height: {LINE_PT}pt; color: #111; margin: 0; }}
h1, h2, h3, p, ul, li, div {{ margin: 0; }}
h1 {{ font-size: {NAME_PT}pt; margin-top: {GAP_PT["name"]}pt; }}
.header {{ color: #444; font-size: {BODY_PT}pt; margin-top: {GAP_PT["header"]}pt; }}
h2 {{ font-size: {SECTION_PT}pt; text-transform: uppercase; border-bottom: 0.75pt solid #999;
      margin-top: {GAP_PT["section"]}pt; padding-bottom: 2pt; }}
h3 {{ font-size: {ENTRY_PT}pt; margin-top: {GAP_PT["entry"]}pt; }}
.meta {{ color: #444; font-size: {BODY_PT}pt; margin-top: {GAP_PT["meta"]}pt; }}
.skill {{ font-size: {BODY_PT}pt; margin-top: {GAP_PT["skill"]}pt; }}
p {{ margin-top: {GAP_PT["para"]}pt; }}
ul {{ padding-left: {BULLET_INDENT_IN}in; font-size: {BODY_PT}pt; list-style-position: outside; }}
li {{ margin-top: {GAP_PT["bullet"]}pt; }}
"""


def render_html(document: Document) -> str:  # noqa: C901 - flat dispatch over the block union
    """Render the same layout as HTML, for print-to-PDF."""
    body: list[str] = []
    in_list = False

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            body.append("</ul>")
            in_list = False

    for block in document.blocks:
        if not isinstance(block, Bullet):
            close_list()
        match block:
            case Name(spans):
                body.append(f"<h1>{spans_to_html(spans)}</h1>")
            case HeaderLine(spans):
                body.append(f'<div class="header">{spans_to_html(spans)}</div>')
            case Section(title):
                body.append(f"<h2>{spans_to_html((Span(title),))}</h2>")
            case Entry(spans):
                body.append(f"<h3>{spans_to_html(spans)}</h3>")
            case Meta(spans):
                body.append(f'<div class="meta">{spans_to_html(spans)}</div>')
            case SkillLine(label, items):
                body.append(
                    f'<div class="skill">{spans_to_html((Span(f"{label}: ", bold=True),))}'
                    f"{spans_to_html(items)}</div>"
                )
            case Bullet(spans):
                if not in_list:
                    body.append("<ul>")
                    in_list = True
                body.append(f"<li>{spans_to_html(spans)}</li>")
            case Paragraph(spans):
                body.append(f"<p>{spans_to_html(spans)}</p>")
            case _:  # pragma: no cover - mypy proves the block union is exhaustive
                assert_never(block)
    close_list()
    return page(document.name or "Resume", CSS, "".join(body))
