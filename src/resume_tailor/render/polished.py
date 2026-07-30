"""The polished layout: a two-column, typographic resume for human readers.

This reproduces the design of the user's own "2026 Polished Resume" — a narrow left rail holding
contact details, skills, and education, separated by a hairline rule from a wide right column
holding the name, summary, and experience.

It is **not** ATS-safe: the two columns are a table, and table layouts get scrambled or dropped
by resume parsers. Send this one to a person; send :mod:`resume_tailor.render.ats` to a portal.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, assert_never, cast

from docx import Document as new_docx
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.shared import Inches, Pt

from resume_tailor.documents.blocks import (
    Bullet,
    Entry,
    HeaderLine,
    Meta,
    Name,
    Paragraph,
    Section,
    SectionGroup,
    SkillLine,
    Span,
)
from resume_tailor.render.docx_common import (
    add_spans,
    set_cell_border,
    set_indent,
    set_line_spacing,
)
from resume_tailor.render.html_common import FONT_STACK, page, spans_to_html

if TYPE_CHECKING:
    from pathlib import Path

    from docx.table import _Cell
    from docx.text.paragraph import Paragraph as DocxParagraph

    from resume_tailor.documents.blocks import Block, Document, GroupBlock

__all__ = ["DEFAULT_SIDEBAR_SECTIONS", "render_docx", "render_html", "split_columns"]

#: Sections that belong in the left rail. Matched case-insensitively against ``## `` headings.
DEFAULT_SIDEBAR_SECTIONS: tuple[str, ...] = (
    "skills",
    "technical core",
    "core competencies",
    "education",
    "certifications",
)

FONT = "Roboto"
FONT_LIGHT = "Roboto ExtraLight"
FONT_SEMIBOLD = "Roboto SemiBold"
BODY_PT = 10.0
CONTACT_PT = 9.0
SECTION_PT = 15.0
NAME_PT = 35.0
LINE_SPACING = 1.15

PAGE_MARGIN_IN = 0.45
SIDEBAR_WIDTH_IN = 2.45
MAIN_WIDTH_IN = 6.05
SIDEBAR_INDENT = (0.45, 0.25)
MAIN_INDENT = (0.30, 0.50)
BULLET_HANGING_IN = 0.18


def _is_contact_line(spans: tuple[Span, ...]) -> bool:
    """Contact lines are the pipe-separated ones; anything else is a target-title subtitle."""
    return "|" in "".join(span.text for span in spans)


def _split_contact(spans: tuple[Span, ...]) -> list[tuple[Span, ...]]:
    """Split a ``a | b | c`` contact line into one stacked entry per item."""
    entries: list[tuple[Span, ...]] = []
    current: list[Span] = []
    for span in spans:
        pieces = span.text.split("|")
        for index, piece in enumerate(pieces):
            if index:
                if current:
                    entries.append(tuple(current))
                current = []
            if text := piece.strip():
                current.append(Span(text, bold=span.bold, italic=span.italic))
    if current:
        entries.append(tuple(current))
    return entries


def split_columns(
    document: Document, sidebar_sections: tuple[str, ...] = DEFAULT_SIDEBAR_SECTIONS
) -> tuple[list[SectionGroup], list[SectionGroup]]:
    """Split ``document`` into (sidebar groups, main groups).

    The preamble is divided by kind rather than by section: the contact line goes to the rail,
    while the name and any target-title line head the main column.
    """
    wanted = {name.casefold() for name in sidebar_sections}
    sidebar: list[SectionGroup] = []
    main: list[SectionGroup] = []
    for group in document.groups():
        if group.title:
            (sidebar if group.key in wanted else main).append(group)
        else:
            preamble_sidebar: list[GroupBlock] = []
            preamble_main: list[GroupBlock] = []
            for block in group.blocks:
                if isinstance(block, HeaderLine) and _is_contact_line(block.spans):
                    preamble_sidebar += [HeaderLine(entry) for entry in _split_contact(block.spans)]
                else:
                    preamble_main.append(block)
            sidebar.append(SectionGroup("", tuple(preamble_sidebar)))
            main.append(SectionGroup("", tuple(preamble_main)))
    return sidebar, main


# --- .docx ----------------------------------------------------------------------------------------
def render_docx(
    document: Document,
    out: Path,
    sidebar_sections: tuple[str, ...] = DEFAULT_SIDEBAR_SECTIONS,
) -> None:
    """Write ``document`` as the two-column polished ``.docx``."""
    docx = new_docx()
    for section in docx.sections:
        section.top_margin = section.bottom_margin = Inches(PAGE_MARGIN_IN)
        section.left_margin = section.right_margin = Inches(0)

    table = docx.add_table(rows=1, cols=2)
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    table.autofit = False
    rail, main = table.rows[0].cells
    for cell, width in ((rail, SIDEBAR_WIDTH_IN), (main, MAIN_WIDTH_IN)):
        cell.width = Inches(width)
    for column, width in zip(table.columns, (SIDEBAR_WIDTH_IN, MAIN_WIDTH_IN), strict=True):
        column.width = Inches(width)
    set_cell_border(rail, "right")

    sidebar_groups, main_groups = split_columns(document, sidebar_sections)
    _fill_cell(rail, sidebar_groups, indent=SIDEBAR_INDENT, sidebar=True)
    _fill_cell(main, main_groups, indent=MAIN_INDENT, sidebar=False)
    docx.save(str(out))


def _fill_cell(
    cell: _Cell,
    groups: list[SectionGroup],
    *,
    indent: tuple[float, float],
    sidebar: bool,
) -> None:
    """Render ``groups`` into a table cell, dropping the empty placeholder paragraph.

    The placeholder only goes once there is something to replace it with: a ``<w:tc>`` with no
    block-level child is invalid per ECMA-376, and Word refuses to open the file. That happens
    for real input — a document with nothing routed to the rail, such as a cover letter with no
    contact line.
    """
    placeholder = cell.paragraphs[0]
    for group in groups:
        if group.title:
            _add(cell, Section(group.title), indent=indent, sidebar=sidebar)
        for block in group.blocks:
            _add(cell, block, indent=indent, sidebar=sidebar)
    if len(cell.paragraphs) > 1:
        cell._tc.remove(placeholder._p)  # noqa: SLF001


def _paragraph(
    cell: _Cell,
    indent: tuple[float, float],
    *,
    hanging: float = 0.0,
    style: str | None = None,
) -> DocxParagraph:
    paragraph = cast("DocxParagraph", cell.add_paragraph(style=style))
    set_indent(paragraph, left=indent[0] + hanging, right=indent[1], hanging=hanging)
    set_line_spacing(paragraph, LINE_SPACING)
    paragraph.paragraph_format.space_before = Pt(0)
    paragraph.paragraph_format.space_after = Pt(0)
    return paragraph


def _lead_in(spans: tuple[Span, ...]) -> bool:
    """Report whether a bullet opens with a bold lead-in, e.g. ``**Data Layer Design:** …``."""
    return bool(spans) and spans[0].bold


def _add(  # noqa: C901 - flat dispatch over the block union
    cell: _Cell, block: Block, *, indent: tuple[float, float], sidebar: bool
) -> None:
    match block:
        case Name(spans):
            paragraph = _paragraph(cell, indent)
            paragraph.paragraph_format.space_after = Pt(4)
            add_spans(paragraph, spans, font=FONT_LIGHT, size=NAME_PT)
        case HeaderLine(spans):
            paragraph = _paragraph(cell, indent)
            paragraph.paragraph_format.space_after = Pt(2)
            if sidebar:
                add_spans(paragraph, spans, font=FONT_SEMIBOLD, size=CONTACT_PT)
            else:
                add_spans(paragraph, spans, font=FONT, size=SECTION_PT * 0.8)
        case Section(title):
            paragraph = _paragraph(cell, indent)
            paragraph.paragraph_format.space_before = Pt(12)
            paragraph.paragraph_format.space_after = Pt(4)
            add_spans(paragraph, (Span(title),), font=FONT, size=SECTION_PT)
        case Entry(spans):
            paragraph = _paragraph(cell, indent)
            paragraph.paragraph_format.space_before = Pt(6)
            add_spans(paragraph, spans, font=FONT_SEMIBOLD, size=BODY_PT, bold=True)
        case Meta(spans):
            paragraph = _paragraph(cell, indent)
            paragraph.paragraph_format.space_after = Pt(3)
            add_spans(paragraph, spans, font=FONT, size=BODY_PT, italic=True)
        case SkillLine(label, items):
            _add_skill(cell, label, items, indent=indent, sidebar=sidebar)
        case Bullet(spans) if _lead_in(spans):
            paragraph = _paragraph(cell, indent)
            paragraph.paragraph_format.space_after = Pt(3)
            add_spans(paragraph, spans, font=FONT, size=BODY_PT)
        case Bullet(spans):
            paragraph = _paragraph(cell, indent, hanging=BULLET_HANGING_IN, style="List Bullet")
            paragraph.paragraph_format.space_after = Pt(2)
            add_spans(paragraph, spans, font=FONT, size=BODY_PT)
        case Paragraph(spans):
            paragraph = _paragraph(cell, indent)
            paragraph.paragraph_format.space_after = Pt(4)
            add_spans(paragraph, spans, font=FONT, size=BODY_PT)
        case _:  # pragma: no cover - mypy proves the block union is exhaustive
            assert_never(block)


def _add_skill(
    cell: _Cell,
    label: str,
    items: tuple[Span, ...],
    *,
    indent: tuple[float, float],
    sidebar: bool,
) -> None:
    """In the rail a skill group stacks one item per line; in the main column it stays inline."""
    if not sidebar:
        paragraph = _paragraph(cell, indent)
        paragraph.paragraph_format.space_after = Pt(2)
        add_spans(paragraph, (Span(f"{label}: "),), font=FONT, size=BODY_PT, bold=True)
        add_spans(paragraph, items, font=FONT, size=BODY_PT)
        return

    heading = _paragraph(cell, indent)
    heading.paragraph_format.space_before = Pt(6)
    heading.paragraph_format.space_after = Pt(1)
    add_spans(heading, (Span(label),), font=FONT, size=BODY_PT, bold=True)
    for item in _skill_items(items):
        paragraph = _paragraph(cell, indent)
        add_spans(paragraph, item, font=FONT, size=BODY_PT)


def _skill_items(items: tuple[Span, ...]) -> list[tuple[Span, ...]]:
    """Split ``a, b (c, d), e`` into items, ignoring commas inside parentheses."""
    entries: list[tuple[Span, ...]] = []
    current: list[Span] = []
    depth = 0
    buffer = ""
    style = Span("")

    def flush_buffer() -> None:
        nonlocal buffer
        if text := buffer.strip():
            current.append(Span(text, bold=style.bold, italic=style.italic))
        buffer = ""

    def flush_item() -> None:
        flush_buffer()
        if current:
            entries.append(tuple(current))
            current.clear()

    for span in items:
        flush_buffer()
        style = span
        for char in span.text:
            if char == "(":
                depth += 1
            elif char == ")":
                depth = max(depth - 1, 0)
            if char == "," and depth == 0:
                flush_item()
            else:
                buffer += char
    flush_item()
    return entries


# --- HTML -----------------------------------------------------------------------------------------
CSS = f"""
@page {{ size: Letter; margin: {PAGE_MARGIN_IN}in 0; }}
* {{ box-sizing: border-box; }}
body {{ font-family: {FONT_STACK}; font-size: {BODY_PT}pt; line-height: {LINE_SPACING};
        color: #111; margin: 0; }}
/* The rule stops where the content does, exactly as the .docx table row does. */
.sheet {{ display: flex; align-items: stretch; }}
.rail {{ width: {SIDEBAR_WIDTH_IN}in; flex: 0 0 {SIDEBAR_WIDTH_IN}in; border-right: 1pt solid #000;
         padding: 0 {SIDEBAR_INDENT[1]}in 0 {SIDEBAR_INDENT[0]}in; }}
.main {{ width: {MAIN_WIDTH_IN}in; flex: 1 1 {MAIN_WIDTH_IN}in;
         padding: 0 {MAIN_INDENT[1]}in 0 {MAIN_INDENT[0]}in; }}
h1 {{ font-size: {NAME_PT}pt; font-weight: 200; margin: 0 0 4pt 0; line-height: 1.05; }}
h2 {{ font-size: {SECTION_PT}pt; font-weight: 400; margin: 12pt 0 4pt 0; }}
h3 {{ font-size: {BODY_PT}pt; font-weight: 600; margin: 6pt 0 0 0; }}
.subtitle {{ font-size: {SECTION_PT * 0.8}pt; margin: 0 0 2pt 0; }}
.contact {{ font-size: {CONTACT_PT}pt; font-weight: 600; margin: 0 0 2pt 0; }}
.meta {{ font-style: italic; margin: 0 0 3pt 0; }}
.skill-group {{ font-weight: 700; margin: 6pt 0 1pt 0; }}
.skill-item {{ margin: 0; }}
.skill-inline {{ margin: 0 0 2pt 0; }}
.lead {{ margin: 0 0 3pt 0; }}
p {{ margin: 0 0 4pt 0; }}
ul {{ margin: 0 0 4pt 0; padding-left: {BULLET_HANGING_IN + 0.06}in; }}
li {{ margin: 0 0 2pt 0; }}
"""


def render_html(
    document: Document, sidebar_sections: tuple[str, ...] = DEFAULT_SIDEBAR_SECTIONS
) -> str:
    """Render the polished layout as HTML, for print-to-PDF."""
    sidebar_groups, main_groups = split_columns(document, sidebar_sections)
    body = (
        '<div class="sheet">'
        f'<aside class="rail">{_html_groups(sidebar_groups, sidebar=True)}</aside>'
        f'<section class="main">{_html_groups(main_groups, sidebar=False)}</section>'
        "</div>"
    )
    return page(document.name or "Resume", CSS, body)


def _html_groups(  # noqa: C901, PLR0912 - flat dispatch over the block union
    groups: list[SectionGroup], *, sidebar: bool
) -> str:
    out: list[str] = []
    in_list = False

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            out.append("</ul>")
            in_list = False

    for group in groups:
        close_list()
        if group.title:
            out.append(f"<h2>{spans_to_html((Span(group.title),))}</h2>")
        for block in group.blocks:
            if not (isinstance(block, Bullet) and not _lead_in(block.spans)):
                close_list()
            match block:
                case Name(spans):
                    out.append(f"<h1>{spans_to_html(spans)}</h1>")
                case HeaderLine(spans):
                    css = "contact" if sidebar else "subtitle"
                    out.append(f'<div class="{css}">{spans_to_html(spans)}</div>')
                case Entry(spans):
                    out.append(f"<h3>{spans_to_html(spans)}</h3>")
                case Meta(spans):
                    out.append(f'<div class="meta">{spans_to_html(spans)}</div>')
                case SkillLine(label, items):
                    out.append(_html_skill(label, items, sidebar=sidebar))
                case Bullet(spans) if _lead_in(spans):
                    out.append(f'<div class="lead">{spans_to_html(spans)}</div>')
                case Bullet(spans):
                    if not in_list:
                        out.append("<ul>")
                        in_list = True
                    out.append(f"<li>{spans_to_html(spans)}</li>")
                case Paragraph(spans):
                    out.append(f"<p>{spans_to_html(spans)}</p>")
                case _:  # pragma: no cover - mypy proves the block union is exhaustive
                    assert_never(block)
    close_list()
    return "".join(out)


def _html_skill(label: str, items: tuple[Span, ...], *, sidebar: bool) -> str:
    if not sidebar:
        return (
            f'<div class="skill-inline">{spans_to_html((Span(f"{label}: ", bold=True),))}'
            f"{spans_to_html(items)}</div>"
        )
    rows = "".join(
        f'<div class="skill-item">{spans_to_html(item)}</div>' for item in _skill_items(items)
    )
    return f'<div class="skill-group">{spans_to_html((Span(label),))}</div>{rows}'
