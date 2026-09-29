"""The resume layout: one column, the design's typography, safe for any parser.

This is the one file to send anywhere. It keeps every property a resume parser depends on — a
single top-to-bottom text flow, standard headings, real bullet lists, contact details in the body
rather than the header region, no tables and no graphics (see ``reference/ATS-PLAYBOOK.md``) —
and sets it in the proportions of the user's own "2026 Polished Resume": a large regular-weight
name, 15pt regular headings, a 10pt body, and a bullet glyph with a 0.25in hanging indent on
every accomplishment. The face is Arial throughout, in the only two weights it has, and a role
heading bolds just the job title (see :mod:`resume_tailor.render.emphasis`). The two-column
arrangement of that design lives in :mod:`resume_tailor.render.polished` as an opt-in for people,
because columns are a table and tables are what parsers scramble.

Arial ships with macOS and Windows, so the PDF printed from the HTML fetches nothing at print time
and Word draws the ``.docx`` in the same face the PDF shows.
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
    is_contact_line,
    is_note,
)
from resume_tailor.render.docx_common import add_spans, set_indent, set_spacing
from resume_tailor.render.emphasis import entry_spans
from resume_tailor.render.html_common import FONT_STACK, page, spans_to_html

if TYPE_CHECKING:
    from pathlib import Path

    from docx.document import Document as DocxDocument
    from docx.text.paragraph import Paragraph as DocxParagraph

    from resume_tailor.documents.blocks import Block, Document

__all__ = ["render_docx", "render_html"]

FONT = "Arial"

BODY_PT = 10.0
PROSE_PT = 11.0
CONTACT_PT = 10.0
SUBTITLE_PT = 12.0
SECTION_PT = 15.0
NAME_PT = 28.0

# Line boxes, absolute so Word and the browser agree (see docx_common.set_spacing). Each is at
# least Arial's natural box at that size, 1.15 times it, and every vertical measure here is a
# multiple of 0.75pt, one CSS pixel, so the browser's whole-pixel snapping never drifts from Word.
LINE_PT = 12.0
PROSE_LINE_PT = 13.5
SUBTITLE_LINE_PT = 14.25
SECTION_LINE_PT = 18.0
NAME_LINE_PT = 33.0

# The gap ABOVE each block. It lives in exactly one property on each side, and the block that
# opens the page gets none.
GAP_PT = {
    "name": 0.0,
    "subtitle": 2.25,
    "contact": 2.25,
    "section": 12.0,
    "section-after-name": 37.5,
    "section-after-header": 21.0,
    "entry": 5.25,
    "meta": 1.5,
    "skill": 2.25,
    "bullet": 2.25,
    "bullet-first": 6.75,
    "note": 2.25,
    "para": 5.25,
}

PAGE_MARGIN_IN = (0.6, 0.7)
"""Top/bottom and left/right page margins."""

BULLET_HANGING_IN = 0.25
NOTE_INDENT_IN = 0.05
BULLET_GLYPH = "•"


# --- the gaps, by what comes before ---------------------------------------------------------------
def _gap(kind: str, previous: Block | None) -> float:
    """Return the space above a block: its kind's gap, or none when it opens the page."""
    return 0.0 if previous is None else GAP_PT[kind]


def _section_kind(previous: Block | None) -> str:
    """Return the gap a heading takes: most directly under the name, less under a header line."""
    if isinstance(previous, Name):
        return "section-after-name"
    if isinstance(previous, HeaderLine):
        return "section-after-header"
    return "section"


def _bullet_kind(previous: Block | None) -> str:
    """Return the gap a bullet takes: the first of a run stands off, the rest sit tighter."""
    return "bullet" if isinstance(previous, Bullet) else "bullet-first"


# --- .docx ----------------------------------------------------------------------------------------
def render_docx(document: Document, out: Path) -> None:
    """Write ``document`` as a single-column, parser-friendly ``.docx``."""
    docx = new_docx()
    _configure(docx)
    previous: Block | None = None
    for block in document.blocks:
        _add_block(docx, block, previous)
        previous = block
    docx.save(str(out))


def _configure(docx: DocxDocument) -> None:
    # Word sizes each line, and the List Bullet glyph (Symbol's bullet from the template's
    # numbering), by the paragraph mark, which takes Normal's font. So Normal carries the body
    # face and size; left at python-docx's Cambria 11pt, lines would stand taller than the PDF's.
    normal = docx.styles["Normal"].font
    normal.name = FONT
    normal.size = Pt(BODY_PT)
    for section in docx.sections:
        section.top_margin = section.bottom_margin = Pt(PAGE_MARGIN_IN[0] * 72)
        section.left_margin = section.right_margin = Pt(PAGE_MARGIN_IN[1] * 72)


def _add_block(  # noqa: C901 - flat dispatch over the block union
    docx: DocxDocument, block: Block, previous: Block | None
) -> None:
    match block:
        case Name(spans):
            paragraph = _paragraph(docx, _gap("name", previous), line=NAME_LINE_PT)
            add_spans(paragraph, spans, font=FONT, size=NAME_PT)
        case HeaderLine(spans) if is_contact_line(spans):
            paragraph = _paragraph(docx, _gap("contact", previous))
            add_spans(paragraph, spans, font=FONT, size=CONTACT_PT)
        case HeaderLine(spans):
            paragraph = _paragraph(docx, _gap("subtitle", previous), line=SUBTITLE_LINE_PT)
            add_spans(paragraph, spans, font=FONT, size=SUBTITLE_PT)
        case Section(title):
            before = _gap(_section_kind(previous), previous)
            paragraph = _paragraph(docx, before, line=SECTION_LINE_PT)
            add_spans(paragraph, (Span(title),), font=FONT, size=SECTION_PT)
        case Entry(spans):
            paragraph = _paragraph(docx, _gap("entry", previous))
            add_spans(paragraph, entry_spans(spans), font=FONT, size=BODY_PT)
        case Meta(spans):
            paragraph = _paragraph(docx, _gap("meta", previous))
            add_spans(paragraph, spans, font=FONT, size=BODY_PT, italic=True)
        case SkillLine(label, items):
            paragraph = _paragraph(docx, _gap("skill", previous))
            add_spans(paragraph, (Span(f"{label}: "),), font=FONT, size=BODY_PT, bold=True)
            add_spans(paragraph, items, font=FONT, size=BODY_PT)
        case Bullet(spans):
            before = _gap(_bullet_kind(previous), previous)
            paragraph = _paragraph(docx, before, style="List Bullet")
            set_indent(paragraph, left=BULLET_HANGING_IN, right=0, hanging=BULLET_HANGING_IN)
            add_spans(paragraph, spans, font=FONT, size=BODY_PT)
        case Paragraph(spans) if is_note(spans):
            paragraph = _paragraph(docx, _gap("note", previous))
            set_indent(paragraph, left=NOTE_INDENT_IN, right=0)
            add_spans(paragraph, spans, font=FONT, size=BODY_PT)
        case Paragraph(spans):
            paragraph = _paragraph(docx, _gap("para", previous), line=PROSE_LINE_PT)
            add_spans(paragraph, spans, font=FONT, size=PROSE_PT)
        case _:  # pragma: no cover - mypy proves the block union is exhaustive
            assert_never(block)


def _paragraph(
    docx: DocxDocument, before: float, *, style: str | None = None, line: float = LINE_PT
) -> DocxParagraph:
    paragraph = docx.add_paragraph(style=style)
    set_spacing(paragraph, before=before, line=line)
    return paragraph


# --- HTML -----------------------------------------------------------------------------------------
CSS = f"""
@page {{ size: Letter; margin: {PAGE_MARGIN_IN[0]}in {PAGE_MARGIN_IN[1]}in; }}
* {{ box-sizing: border-box; }}
/* Every gap is a margin-TOP and every bottom margin is 0, so CSS collapsing and Word's additive
   spacing produce the same number. line-height is absolute for the same reason. */
body {{ font-family: {FONT_STACK}; font-size: {BODY_PT}pt; line-height: {LINE_PT}pt;
        color: #111; margin: 0; }}
/* Arial has two weights, regular and bold, which is also all a .docx run can say, so no rule
   here names a weight between them. An entry heading's bold comes from its spans, as in Word. */
h1, h2, h3, p, ul, li, div {{ margin: 0; }}
h1 {{ font-size: {NAME_PT}pt; font-weight: 400; line-height: {NAME_LINE_PT}pt;
      margin-top: {GAP_PT["name"]}pt; }}
.subtitle {{ font-size: {SUBTITLE_PT}pt; line-height: {SUBTITLE_LINE_PT}pt;
             margin-top: {GAP_PT["subtitle"]}pt; }}
.contact {{ font-size: {CONTACT_PT}pt; margin-top: {GAP_PT["contact"]}pt; }}
h2 {{ font-size: {SECTION_PT}pt; font-weight: 400; line-height: {SECTION_LINE_PT}pt;
      margin-top: {GAP_PT["section"]}pt; }}
h1 + h2 {{ margin-top: {GAP_PT["section-after-name"]}pt; }}
.subtitle + h2, .contact + h2 {{ margin-top: {GAP_PT["section-after-header"]}pt; }}
h3 {{ font-size: {BODY_PT}pt; font-weight: 400; margin-top: {GAP_PT["entry"]}pt; }}
.meta {{ font-style: italic; margin-top: {GAP_PT["meta"]}pt; }}
.skill {{ margin-top: {GAP_PT["skill"]}pt; }}
p {{ font-size: {PROSE_PT}pt; line-height: {PROSE_LINE_PT}pt; margin-top: {GAP_PT["para"]}pt; }}
p.note {{ font-size: {BODY_PT}pt; line-height: {LINE_PT}pt; padding-left: {NOTE_INDENT_IN}in;
          margin-top: {GAP_PT["note"]}pt; }}
/* Every bullet draws its glyph at the margin and hangs its text past it, like the .docx
   "List Bullet" paragraphs. The first of a run stands off from what precedes it. */
ul {{ padding: 0; list-style: none; }}
li {{ position: relative; padding-left: {BULLET_HANGING_IN}in; margin-top: {GAP_PT["bullet"]}pt; }}
li:first-child {{ margin-top: {GAP_PT["bullet-first"]}pt; }}
li::before {{ content: "{BULLET_GLYPH}"; position: absolute; left: 0; }}
body > :first-child {{ margin-top: 0; }}
"""


def render_html(document: Document) -> str:
    """Render the same layout as HTML, for print-to-PDF."""
    body: list[str] = []
    in_list = False
    for block in document.blocks:
        if isinstance(block, Bullet) != in_list:
            body.append("<ul>" if in_list is False else "</ul>")
            in_list = not in_list
        body.append(_html_block(block))
    if in_list:
        body.append("</ul>")
    return page(document.name or "Resume", CSS, "".join(body))


def _html_block(block: Block) -> str:
    """Render one block; a bullet comes back as a bare ``<li>`` for the caller's list."""
    match block:
        case Name(spans):
            html = f"<h1>{spans_to_html(spans)}</h1>"
        case HeaderLine(spans):
            css = "contact" if is_contact_line(spans) else "subtitle"
            html = f'<div class="{css}">{spans_to_html(spans)}</div>'
        case Section(title):
            html = f"<h2>{spans_to_html((Span(title),))}</h2>"
        case Entry(spans):
            html = f"<h3>{spans_to_html(entry_spans(spans))}</h3>"
        case Meta(spans):
            html = f'<div class="meta">{spans_to_html(spans)}</div>'
        case SkillLine(label, items):
            html = (
                f'<div class="skill">{spans_to_html((Span(f"{label}: ", bold=True),))}'
                f"{spans_to_html(items)}</div>"
            )
        case Bullet(spans):
            html = f"<li>{spans_to_html(spans)}</li>"
        case Paragraph(spans) if is_note(spans):
            html = f'<p class="note">{spans_to_html(spans)}</p>'
        case Paragraph(spans):
            html = f"<p>{spans_to_html(spans)}</p>"
        case _:  # pragma: no cover - mypy proves the block union is exhaustive
            assert_never(block)
    return html
