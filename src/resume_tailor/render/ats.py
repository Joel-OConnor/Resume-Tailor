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
from resume_tailor.render.docx_common import add_spans, set_bottom_border
from resume_tailor.render.html_common import page, spans_to_html

if TYPE_CHECKING:
    from pathlib import Path

    from docx.document import Document as DocxDocument

    from resume_tailor.documents.blocks import Block, Document

__all__ = ["render_docx", "render_html"]

FONT = "Calibri"
BODY_PT = 10.0
PROSE_PT = 10.5
NAME_PT = 20.0
SECTION_PT = 12.0
ENTRY_PT = 11.0
MUTED = "444444"


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
            paragraph = docx.add_paragraph()
            paragraph.paragraph_format.space_after = Pt(2)
            add_spans(paragraph, spans, font=FONT, size=NAME_PT, bold=True)
        case HeaderLine(spans):
            paragraph = docx.add_paragraph()
            paragraph.paragraph_format.space_after = Pt(1)
            add_spans(paragraph, spans, font=FONT, size=BODY_PT, color=MUTED)
        case Section(title):
            paragraph = docx.add_paragraph()
            paragraph.paragraph_format.space_before = Pt(10)
            paragraph.paragraph_format.space_after = Pt(3)
            add_spans(paragraph, (Span(title.upper()),), font=FONT, size=SECTION_PT, bold=True)
            set_bottom_border(paragraph)
        case Entry(spans):
            paragraph = docx.add_paragraph()
            paragraph.paragraph_format.space_before = Pt(7)
            paragraph.paragraph_format.space_after = Pt(0)
            add_spans(paragraph, spans, font=FONT, size=ENTRY_PT, bold=True)
        case Meta(spans):
            paragraph = docx.add_paragraph()
            paragraph.paragraph_format.space_after = Pt(2)
            add_spans(paragraph, spans, font=FONT, size=BODY_PT, italic=True, color=MUTED)
        case SkillLine(label, items):
            paragraph = docx.add_paragraph()
            paragraph.paragraph_format.space_after = Pt(1)
            add_spans(paragraph, (Span(f"{label}: "),), font=FONT, size=BODY_PT, bold=True)
            add_spans(paragraph, items, font=FONT, size=BODY_PT)
        case Bullet(spans):
            paragraph = docx.add_paragraph(style="List Bullet")
            paragraph.paragraph_format.space_after = Pt(1)
            add_spans(paragraph, spans, font=FONT, size=BODY_PT)
        case Paragraph(spans):
            paragraph = docx.add_paragraph()
            paragraph.paragraph_format.space_after = Pt(4)
            add_spans(paragraph, spans, font=FONT, size=PROSE_PT)
        case _:  # pragma: no cover - mypy proves the block union is exhaustive
            assert_never(block)


CSS = """
@page { size: Letter; margin: 0.6in 0.7in; }
* { box-sizing: border-box; }
body { font-family: Calibri, Helvetica, Arial, sans-serif; font-size: 10.5pt; line-height: 1.3;
       color: #111; margin: 0; }
h1 { font-size: 20pt; margin: 0 0 2pt 0; }
.header { color: #444; font-size: 10pt; margin: 0 0 1pt 0; }
h2 { font-size: 12pt; text-transform: uppercase; border-bottom: 1px solid #999;
     margin: 12pt 0 4pt 0; padding-bottom: 2pt; }
h3 { font-size: 11pt; margin: 8pt 0 0 0; }
.meta { color: #444; font-size: 10pt; margin: 0 0 2pt 0; }
.skill { font-size: 10pt; margin: 0 0 1pt 0; }
p { margin: 0 0 5pt 0; }
ul { margin: 2pt 0 4pt 0; padding-left: 18pt; font-size: 10pt; }
li { margin: 0 0 1pt 0; }
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
